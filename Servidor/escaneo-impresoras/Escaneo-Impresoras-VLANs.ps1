# Escaneo-Impresoras-VLANs.ps1
# Escanea impresoras SNMP (Sharp/Lexmark/Brother/etc.) en las VLANs indicadas,
# reporta avance en tiempo real a un archivo JSON, y exporta CSV final.
#
# VLAN 100: 10.70.29.1  - 10.70.29.253
# VLAN 101: 10.71.4.1   - 10.71.5.253
# VLAN 102: 10.70.18.1  - 10.70.18.253

param(
    [ValidatePattern('^(?!-)[A-Za-z0-9_.@!#%^*+=:\-]{1,64}$')]
    [string]$Community = "public",
    [string]$Salida = ".\Inventario_Impresoras_VLANs.csv",
    [string]$ArchivoProgreso = ".\progreso_escaneo.json",
    [int]$TimeoutMs = 800,
    [int]$MaxParalelo = 30,
    [ValidatePattern('^\d{1,4}(,\d{1,4})*$')]
    [string]$VlansCsv = "100,101,102"
)

if (-not $PSBoundParameters.ContainsKey('Community') -and $env:SNMP_COMMUNITY) {
    if ($env:SNMP_COMMUNITY -match '^(?!-)[A-Za-z0-9_.@!#%^*+=:\-]{1,64}$') { $Community = $env:SNMP_COMMUNITY }
    else { Write-Host "SNMP_COMMUNITY invalida" -ForegroundColor Red; exit 1 }
}

$Vlans = $VlansCsv -split ","

$TodosLosRangos = @(
    @{ VLAN = "100"; Inicio = "10.70.29.1"; Fin = "10.70.29.253" }
    @{ VLAN = "101"; Inicio = "10.71.4.1";  Fin = "10.71.5.253" }
    @{ VLAN = "102"; Inicio = "10.70.18.1"; Fin = "10.70.18.253" }
)

$Rangos = $TodosLosRangos | Where-Object { $Vlans -contains $_.VLAN }

if ($Rangos.Count -eq 0) {
    Write-Host "No se seleccionó ninguna VLAN válida." -ForegroundColor Red
    exit 1
}

function ConvertTo-UInt32FromIP {
    param([string]$IP)
    $bytes = $IP.Split('.') | ForEach-Object { [byte]$_ }
    [array]::Reverse($bytes)
    return [BitConverter]::ToUInt32($bytes, 0)
}

function ConvertTo-IPFromUInt32 {
    param([uint32]$Num)
    $bytes = [BitConverter]::GetBytes($Num)
    [array]::Reverse($bytes)
    return ($bytes -join '.')
}

function Guardar-Progreso {
    param($VlanActual, $IpActual, $Revisadas, $Total, $Encontradas)
    $obj = [PSCustomObject]@{
        estado             = "corriendo"
        vlan_actual        = $VlanActual
        ip_actual          = $IpActual
        ips_revisadas      = $Revisadas
        ips_totales        = $Total
        impresoras_encontradas = $Encontradas
        actualizado        = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
    $obj | ConvertTo-Json | Set-Content -Path $ArchivoProgreso -Encoding UTF8
}

$OID_SERIAL   = ".1.3.6.1.2.1.43.5.1.1.17.1"
$OID_SYSDESCR = ".1.3.6.1.2.1.1.1.0"
$OID_SYSNAME  = ".1.3.6.1.2.1.1.5.0"

$resultados = New-Object System.Collections.Generic.List[Object]

$totalIPs = 0
foreach ($r in $Rangos) {
    $totalIPs += (ConvertTo-UInt32FromIP $r.Fin) - (ConvertTo-UInt32FromIP $r.Inicio) + 1
}
$revisadas = 0

foreach ($rango in $Rangos) {

    $vlan   = $rango.VLAN
    $numIni = ConvertTo-UInt32FromIP $rango.Inicio
    $numFin = ConvertTo-UInt32FromIP $rango.Fin

    Write-Host "`n=== Escaneando VLAN $vlan ($($rango.Inicio) a $($rango.Fin)) ===" -ForegroundColor Cyan

        # Fase 1: ping en paralelo para descartar rapido las IPs sin equipo
    $ipsRango = @(for ($n = $numIni; $n -le $numFin; $n++) { ConvertTo-IPFromUInt32 $n })

    $pool = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspacePool(1, $MaxParalelo)
    $pool.Open()

    $pingJobs = @(foreach ($ipTest in $ipsRango) {
        $psInst = [System.Management.Automation.PowerShell]::Create()
        $psInst.RunspacePool = $pool
        [void]$psInst.AddScript({
            param($ip)
            Test-Connection -ComputerName $ip -Count 1 -Quiet -ErrorAction SilentlyContinue
        }).AddArgument($ipTest)
        [PSCustomObject]@{ IP = $ipTest; PS = $psInst; Handle = $psInst.BeginInvoke() }
    })

    while (@($pingJobs | Where-Object { -not $_.Handle.IsCompleted }).Count -gt 0) {
        Start-Sleep -Milliseconds 200
        $completados = @($pingJobs | Where-Object { $_.Handle.IsCompleted }).Count
        Guardar-Progreso -VlanActual $vlan -IpActual "ping ($completados/$($ipsRango.Count))" -Revisadas ($revisadas + $completados) -Total $totalIPs -Encontradas $resultados.Count
    }

    $vivos = New-Object System.Collections.Generic.List[string]
    foreach ($j in $pingJobs) {
        $ok = $j.PS.EndInvoke($j.Handle)
        if ($ok) { $vivos.Add($j.IP) }
        $j.PS.Dispose()
    }
    $pool.Close()
    $pool.Dispose()

    $revisadas += $ipsRango.Count
    Guardar-Progreso -VlanActual $vlan -IpActual "" -Revisadas $revisadas -Total $totalIPs -Encontradas $resultados.Count

    # Fase 2: SNMP secuencial, solo para las IPs que si respondieron
    foreach ($ip in $vivos) {
            Guardar-Progreso -VlanActual $vlan -IpActual "snmp $ip" -Revisadas $revisadas -Total $totalIPs -Encontradas $resultados.Count
        try {
            $snmp = New-Object -ComObject olePrn.OleSNMP
            $snmp.Open($ip, $Community, 2, $TimeoutMs)

            $serial = $null
            $modelo = $null
            $nombre = $null

            try { $serial = $snmp.Get($OID_SERIAL) } catch {}
            try { $modelo = $snmp.Get($OID_SYSDESCR) } catch {}
            try { $nombre = $snmp.Get($OID_SYSNAME) } catch {}

            $snmp.Close()

            if (-not $serial -and -not $modelo) { continue }

            $obj = [PSCustomObject]@{
                VLAN          = $vlan
                IP            = $ip
                Nombre_Red    = $nombre
                Modelo_Marca  = $modelo
                NumeroSerie   = $serial
                FechaEscaneo  = (Get-Date -Format "yyyy-MM-dd HH:mm")
            }

            $resultados.Add($obj)
            Write-Host "[OK] $ip -> Serie: $serial | $modelo" -ForegroundColor Green
            Guardar-Progreso -VlanActual $vlan -IpActual "snmp $ip" -Revisadas $revisadas -Total $totalIPs -Encontradas $resultados.Count

        } catch {
            continue
        }
    }
}

Guardar-Progreso -VlanActual "finalizando" -IpActual "" -Revisadas $totalIPs -Total $totalIPs -Encontradas $resultados.Count

if ($resultados.Count -eq 0) {
    Write-Host "`nNo se encontraron impresoras con SNMP activo en las VLANs seleccionadas." -ForegroundColor Yellow
} else {
    $resultados | Export-Csv -Path $Salida -NoTypeInformation -Encoding UTF8
    Write-Host "`nListo. $($resultados.Count) impresoras encontradas en total. CSV guardado en: $Salida" -ForegroundColor Cyan
}

$final = [PSCustomObject]@{
    estado             = "listo"
    vlan_actual        = ""
    ip_actual          = ""
    ips_revisadas      = $totalIPs
    ips_totales        = $totalIPs
    impresoras_encontradas = $resultados.Count
    actualizado        = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
}
$final | ConvertTo-Json | Set-Content -Path $ArchivoProgreso -Encoding UTF8
