# Crea la tarea programada que sincroniza tus subastas cada 15 minutos.
#
# Usa pythonw.exe (sin ventana) para que no te salte una consola mientras
# juegas. Para quitarla:
#
#   schtasks /delete /tn "WoW subastas sync" /f

$ErrorActionPreference = "Stop"

$proyecto = $PSScriptRoot
$python = Join-Path $proyecto ".venv\Scripts\pythonw.exe"
$script = Join-Path $proyecto "sync_subastas.py"

if (-not (Test-Path $python)) {
    throw "No encuentro $python. Crea el entorno virtual primero (ver README)."
}

# La tarea arranca en la carpeta del proyecto: git necesita estar dentro del
# repositorio para poder commitear.
$comando = "cmd /c cd /d `"$proyecto`" && `"$python`" `"$script`""

schtasks /create `
    /tn "WoW subastas sync" `
    /tr $comando `
    /sc minute `
    /mo 15 `
    /f

Write-Host ""
Write-Host "Tarea creada. Comprueba que funciona con:" -ForegroundColor Green
Write-Host "  schtasks /run /tn `"WoW subastas sync`""
Write-Host ""
Write-Host "Y mira el resultado con:" -ForegroundColor Green
Write-Host "  git log --oneline -3"
