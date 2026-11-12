# diagnostico_sasi.ps1
# Prueba la conexion a sm.php con tus credenciales
# Ejecutar: powershell -ExecutionPolicy Bypass -File .\diagnostico_sasi.ps1

param(
    [string]$Usuario  = "acorreab",
    [string]$Password = "",
    [string]$Dominio  = "cjf",
    [string]$Url      = "http://10.2.171.6/sasi/sm.php"
)

if (-not $Password) {
    $secPass = Read-Host "Contrasena para $Dominio\$Usuario" -AsSecureString
    $cred    = New-Object System.Management.Automation.PSCredential("tmp", $secPass)
    $Password = $cred.GetNetworkCredential().Password
}

Write-Host "=== 1) Verificando conectividad a sm.php ===" -ForegroundColor Cyan
try {
    $ping = Invoke-WebRequest -Uri $Url -Method HEAD -TimeoutSec 5 -ErrorAction Stop
    Write-Host "OK  sm.php responde (HTTP $($ping.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "ERROR: No se llego a $Url" -ForegroundColor Red
    Write-Host $_.Exception.Message
    return
}

Write-Host "`n=== 2) Login con credenciales ===" -ForegroundColor Cyan
$body = @{
    user     = $Usuario
    password = $Password
    domain   = $Dominio
    action   = "list"
}
try {
    $resp = Invoke-WebRequest -Uri $Url -Method POST -Body $body -TimeoutSec 15 -ErrorAction Stop
    Write-Host "HTTP Status: $($resp.StatusCode)" -ForegroundColor Green
    Write-Host "`n=== 3) Primeros 1000 chars de la respuesta ===" -ForegroundColor Cyan
    Write-Host $resp.Content.Substring(0, [Math]::Min(1000, $resp.Content.Length))
    Write-Host "`n=== 4) Guardando respuesta completa en sasi_response.txt ===" -ForegroundColor Cyan
    $resp.Content | Out-File -FilePath "sasi_response.txt" -Encoding utf8
    Write-Host "OK  Guardado en sasi_response.txt" -ForegroundColor Green
} catch {
    Write-Host "ERROR al llamar sm.php:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    if ($_.Exception.Response) {
        Write-Host "HTTP Status: $($_.Exception.Response.StatusCode.value__)"
    }
}
Write-Host "`n=== FIN DIAGNOSTICO ===" -ForegroundColor Cyan
