# Crea la tarea programada que sincroniza tus subastas cada 15 minutos.
#
# Usa pythonw.exe (sin ventana) para que no te salte una consola mientras
# juegas. Para quitarla:
#
#   Unregister-ScheduledTask -TaskName "WoW subastas sync" -Confirm:$false

$ErrorActionPreference = "Stop"

$nombre = "WoW subastas sync"
$proyecto = $PSScriptRoot
$python = Join-Path $proyecto ".venv\Scripts\pythonw.exe"
$script = Join-Path $proyecto "sync_subastas.py"

if (-not (Test-Path $python)) {
    throw "No encuentro $python. Crea el entorno virtual primero (ver README)."
}
if (-not (Test-Path $script)) {
    throw "No encuentro $script."
}

# Con los cmdlets y no con schtasks.exe: las rutas llevan espacios, y schtasks
# parte el comando por su cuenta en cuanto los ve.
$accion = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`"" `
    -WorkingDirectory $proyecto

# Un unico disparador que se repite indefinidamente. La primera pasada sale un
# minuto despues de instalarla, para poder comprobar que funciona sin esperar.
$disparador = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

# Que se ejecute tambien con el portatil a bateria, y que recupere la pasada
# perdida si el equipo estaba apagado a su hora.
$ajustes = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $nombre `
    -Action $accion `
    -Trigger $disparador `
    -Settings $ajustes `
    -Description "Sube a GitHub las subastas que exporta el addon WowAlertsExport." `
    -Force | Out-Null

# Comprobar de verdad que existe, en vez de fiarse de que no haya saltado nada.
$tarea = Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
if (-not $tarea) {
    throw "La tarea no se ha creado. Revisa los permisos de tu usuario."
}

Write-Host ""
Write-Host "Tarea '$nombre' creada y verificada." -ForegroundColor Green
Write-Host "  Ejecuta:  $python"
Write-Host "  Con:      $script"
Write-Host "  Cada:     15 minutos"
Write-Host ""
Write-Host "Para lanzarla ahora mismo:" -ForegroundColor Green
Write-Host "  Start-ScheduledTask -TaskName `"$nombre`""
Write-Host ""
Write-Host "Para quitarla:" -ForegroundColor Green
Write-Host "  Unregister-ScheduledTask -TaskName `"$nombre`" -Confirm:`$false"
