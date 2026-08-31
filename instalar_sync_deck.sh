#!/usr/bin/env bash
# Instala en la Steam Deck la sincronizacion de subastas cada 15 minutos.
#
# Usa un timer de systemd de usuario, que es el equivalente a la tarea
# programada de Windows y no necesita permisos de administrador ni tocar el
# sistema de solo lectura de SteamOS.
#
# Para quitarlo:
#   systemctl --user disable --now wow-subastas-sync.timer
set -euo pipefail

proyecto="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unidades="$HOME/.config/systemd/user"

if [ ! -f "$proyecto/sync_subastas.py" ]; then
    echo "No encuentro sync_subastas.py en $proyecto" >&2
    exit 1
fi

python="$(command -v python3 || true)"
if [ -z "$python" ]; then
    echo "No encuentro python3. Instalalo antes de seguir." >&2
    exit 1
fi

mkdir -p "$unidades"

cat > "$unidades/wow-subastas-sync.service" <<UNIDAD
[Unit]
Description=Sube a GitHub las subastas que exporta el addon WowAlertsExport
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$proyecto
ExecStart=$python $proyecto/sync_subastas.py --maquina deck
UNIDAD

cat > "$unidades/wow-subastas-sync.timer" <<UNIDAD
[Unit]
Description=Sincroniza las subastas de WoW cada 15 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
# Recupera la pasada perdida si la Deck estaba suspendida a su hora.
Persistent=true

[Install]
WantedBy=timers.target
UNIDAD

systemctl --user daemon-reload
systemctl --user enable --now wow-subastas-sync.timer

echo
echo "Timer instalado. Comprueba que funciona con:"
echo "  systemctl --user start wow-subastas-sync.service"
echo "  journalctl --user -u wow-subastas-sync.service -n 20"
echo
echo "Y cuando se ejecutara con:"
echo "  systemctl --user list-timers wow-subastas-sync.timer"
