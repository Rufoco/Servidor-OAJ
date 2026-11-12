# Escaneo-Impresoras-IPs.ps1
# Escanea una lista de IPs (una por linea en -ArchivoIps) con el mismo metodo que
# Escaneo-Impresoras-VLANs.ps1: ping en paralelo + consulta SNMP a las que responden.

param(
    [string]$Community = "public",
    [Parameter(Mandatory = $true)][string]$ArchivoIps,
    [string]$Salida = ".\Inventario_Impresoras_IPs.csv",
    [string]$ArchivoProgreso = ".\progreso_ips.json",
    [int]$TimeoutMs = 800,
    [int]$MaxParalelo = 30
)

# OIDs: valores por defecto; si existe el script de VLANs se leen de ahi para usar EXACTAMENTE los mismos
$OID_SERIAL   = ".1.3.6.1.2.1.43.5.1.1.17.1"
$OID_SYSDESCR = ".1.3.6.1.2.1.1.1.0"
$OID_SYSNAME  = ".1.3.6.1.2.1.1.5.0"

$scriptVlans = Join-Path $PSScriptRoot "Escaneo-Impresoras-VLANs.ps1"
if (Test-Path $scriptVlans) {
    Get-Content $scriptVlans |
        Where-Object { $_ -match '^\s*\$OID_(SERIAL|SYSDESCR|SYSNAME)\s*=\s*"[^"]+"\s*(#.*)?$' } |
        ForEach-Object { Invoke-Expression $_ }
}

$ips = @(Get-Content $ArchivoIps |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' } |
    Select-Object -Unique)
$total = $ips.Count

$vlansConocidas = @(
    @{ VLAN = "100"; Inicio = "10.70.29.1"; Fin = "10.70.29.253" }
    @{ VLAN = "101"; Inicio = "10.71.4.1";  Fin = "10.71.5.253" }
    @{ VLAN = "102"; Inicio = "10.70.18.1"; Fin = "10.70.18.253" }
)

function ConvertTo-UInt32FromIP {
    param([string]$IP)
    $bytes = [byte[]]($IP.Split('.') | ForEach-Object { [byte]$_ })
    [array]::Reverse($bytes)
    return [BitConverter]::ToUInt32($bytes, 0)
}

function Get-VlanDeIP {
    param([string]$IP)
    try {
        $n = ConvertTo-UInt32FromIP $IP
        foreach ($v in $vlansConocidas) {
            if ($n -ge (ConvertTo-UInt32FromIP $v.Inicio) -and $n -le (ConvertTo-UInt32FromIP $v.Fin)) {
                return $v.VLAN
            }
        }
    } catch {}
    return "-"
}

function Guardar-Progreso {
    param(
        [string]$Estado = "corriendo",
        [string]$Fase = "",
        [int]$Hecho = 0,
        [int]$De = 0,
        [string]$IpActual = "",
        [int]$Encontradas = 0
    )
    $obj = [PSCustomObject]@{
        estado                 = $Estado
        fase                   = $Fase
        hecho                  = $Hecho
        de                     = $De
        ip_actual              = $IpActual
        impresoras_encontradas = $Encontradas
        actualizado            = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
    $obj | ConvertTo-Json | Set-Content -Path $ArchivoProgreso -Encoding UTF8
}

# Una fila por cada IP pegada, con estado por defecto "Sin respuesta (ping)"
$fecha = (Get-Date -Format "yyyy-MM-dd HH:mm")
$filas = @{}
foreach ($ip in $ips) {
    $filas[$ip] = [PSCustomObject]@{
        VLAN         = (Get-VlanDeIP $ip)
        IP           = $ip
        Nombre_Red   = ""
        Modelo_Marca = ""
        NumeroSerie  = ""
        Estado       = "Sin respuesta (ping)"
        FechaEscaneo = $fecha
    }
}

# Fase 1: ping en paralelo
Guardar-Progreso -Fase "ping" -Hecho 0 -De $total

$pool = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspacePool(1, $MaxParalelo)
$pool.Open()

$pingJobs = @(foreach ($ipTest in $ips) {
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
    $listos = @($pingJobs | Where-Object { $_.Handle.IsCompleted }).Count
    Guardar-Progreso -Fase "ping" -Hecho $listos -De $total
}

$vivos = New-Object System.Collections.Generic.List[string]
foreach ($j in $pingJobs) {
    $ok = $j.PS.EndInvoke($j.Handle)
    if ($ok) { $vivos.Add($j.IP) }
    $j.PS.Dispose()
}
$pool.Close()
$pool.Dispose()

# Fase 2: SNMP secuencial, solo para las IPs que respondieron al ping
$encontradas = 0
$i = 0
foreach ($ip in $vivos) {
    $i++
    Guardar-Progreso -Fase "snmp" -Hecho $i -De $vivos.Count -IpActual $ip -Encontradas $encontradas
    $fila = $filas[$ip]
    $fila.Estado = "Sin datos SNMP"
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

        if ($serial -or $modelo) {
            $fila.Nombre_Red   = [string]$nombre
            $fila.Modelo_Marca = [string]$modelo
            $fila.NumeroSerie  = [string]$serial
            $fila.Estado       = "OK"
            $encontradas++
            Write-Host "[OK] $ip -> Serie: $serial | $modelo" -ForegroundColor Green
        }
    } catch {
        continue
    }
}

$ips | ForEach-Object { $filas[$_] } | Export-Csv -Path $Salida -NoTypeInformation -Encoding UTF8
Guardar-Progreso -Estado "listo" -Fase "fin" -Hecho $total -De $total -Encontradas $encontradas
Write-Host "`nListo. $encontradas impresoras con datos de $total IPs. CSV: $Salida" -ForegroundColor Cyan
