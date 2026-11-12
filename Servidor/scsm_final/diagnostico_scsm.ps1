# ============================================================================
# diagnostico_scsm.ps1  —  Diagnóstico de "Mis Reportes" SCSM
# Ejecutar en el servidor del portal, con la MISMA cuenta con la que corres
# python scsm_server_portal.py:
#
#   powershell -ExecutionPolicy Bypass -File .\diagnostico_scsm.ps1 -Usuario acorreab
#
# (cambia "acorreab" por tu UserName si fuera distinto)
# ============================================================================

param(
    [string]$Usuario = "acorreab",
    [string]$Servidor = "10.240.2.12",
    [string]$Modulo  = "D:\System Manager\PowerShell\System.Center.Service.Manager.psd1"
)

$ErrorActionPreference = "Stop"

Write-Host "=== 1) Importando módulo SCSM ===" -ForegroundColor Cyan
Import-Module $Modulo
Write-Host "OK módulo importado." -ForegroundColor Green

Write-Host "`n=== 2) Conectando al management group ($Servidor) con la identidad actual ===" -ForegroundColor Cyan
New-SCManagementGroupConnection -ComputerName $Servidor | Out-Null
$mg = Get-SCManagementGroup
Write-Host ("OK conectado. Identidad del proceso: {0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -ForegroundColor Green

Write-Host "`n=== 3) Buscando objetos System.Domain.User que coincidan con '$Usuario' ===" -ForegroundColor Cyan
$claseUser = Get-SCClass -Name 'System.Domain.User'
$reader = $mg.GetObjectReader($claseUser,
            [Microsoft.EnterpriseManagement.Common.ObjectQueryOptions]::Default)

$coincidencias = @()
$total = 0
while ($reader.Read()) {
    $total++
    $obj   = $reader.Current
    $uname = try { "$($obj['UserName'].Value)" }    catch { '' }
    $dom   = try { "$($obj['Domain'].Value)" }       catch { '' }
    $dname = try { "$($obj['DisplayName'].Value)" }  catch { '' }
    if ($uname -like "*$Usuario*" -or $dname -like "*$Usuario*") {
        $coincidencias += [PSCustomObject]@{ Domain=$dom; UserName=$uname; DisplayName=$dname; Obj=$obj }
    }
}
Write-Host ("Usuarios totales en el directorio SCSM: {0}" -f $total)
Write-Host ("Coincidencias con '$Usuario': {0}" -f $coincidencias.Count) -ForegroundColor Yellow
$coincidencias | Select-Object Domain, UserName, DisplayName | Format-Table -AutoSize

if ($coincidencias.Count -eq 0) {
    Write-Host "`n>>> No se encontró tu usuario en SCSM con ese criterio." -ForegroundColor Red
    Write-Host ">>> Revisa el UserName/Domain reales arriba y vuelve a ejecutar con -Usuario <correcto>." -ForegroundColor Red
    return
}

Write-Host "`n=== 4) Work items donde el usuario es AffectedUser ===" -ForegroundColor Cyan
$relAfectado = Get-SCRelationship -Name 'System.WorkItemAffectedUser'
foreach ($c in $coincidencias) {
    Write-Host ("`n-- {0}\{1} ({2}) --" -f $c.Domain, $c.UserName, $c.DisplayName) -ForegroundColor Yellow
    $items = Get-SCRelatedObjectsWhereTarget -SMObject $c.Obj -Relationship $relAfectado
    if (-not $items -or $items.Count -eq 0) {
        Write-Host "   (sin work items con AffectedUser)" -ForegroundColor DarkYellow
        continue
    }
    foreach ($it in $items) {
        $cls = try { "$($it.GetLeastDerivedNonAbstractClass().Name)" } catch { '?' }
        $est = try { "$($it.Status.DisplayName)" } catch { '' }
        Write-Host ("   [{0}] {1}  Estado='{2}'  Clase={3}" -f $it.Id, $it.Title, $est, $cls)
    }
}

Write-Host "`n=== FIN DIAGNÓSTICO ===" -ForegroundColor Cyan
