"""Revisa si el vigilante se esta ejecutando de verdad en GitHub Actions.

Responde a la pregunta que no contesta Discord: cuando no llega ningun aviso,
puede ser que no haya chollos... o que la pasada no se haya ejecutado. Aqui se
ven las dos cosas por separado, incluidos los huecos del horario.

Necesita el cliente `gh` instalado y autenticado.

    py estado.py                # ultimas 24 horas
    py estado.py --horas 48
    py estado.py --detalle      # ademas, el resumen del log de cada pasada
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

WORKFLOW = "WoW Price Monitor"
# Minuto en el que el cron pide la ejecucion (ver .github/workflows/monitor.yml).
MINUTO_CRON = 35

SIMBOLO = {"success": "✓", "failure": "✗", "cancelled": "-", None: "…"}


class GhError(Exception):
    """No se ha podido hablar con GitHub."""


def gh(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise GhError(
            "No encuentro el comando 'gh'. Instala GitHub CLI desde https://cli.github.com"
        ) from exc
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip()[:300])
    return proc.stdout


def listar_runs(limite: int) -> list[dict]:
    salida = gh(
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--limit",
        str(limite),
        "--json",
        "databaseId,event,conclusion,status,startedAt",
    )
    return json.loads(salida)


def resumen_del_log(run_id: int) -> str:
    """Extrae del log la linea que dice que encontro la pasada."""
    try:
        log = gh("run", "view", str(run_id), "--log")
    except GhError:
        return "(log no disponible)"

    if "Ningun chollo nuevo" in log:
        return "sin chollos nuevos"
    enviados = re.search(r"Enviados a Discord (\d+) chollo", log)
    if enviados:
        return f"{enviados.group(1)} chollo(s) enviados"
    if "--dry-run" in log:
        return "pasada en seco"
    return "(sin resumen)"


def slot_de(inicio: datetime) -> datetime:
    """Hora del cron a la que corresponde una ejecucion.

    GitHub lanza tarde pero nunca antes, asi que una ejecucion a las 15:52 es
    la del slot de las 15:35, y una a las 15:10 es la del slot de las 14:35.
    """
    slot = inicio.replace(minute=MINUTO_CRON, second=0, microsecond=0)
    if inicio.minute < MINUTO_CRON:
        slot -= timedelta(hours=1)
    return slot


def slots_esperados(ahora: datetime, horas: int) -> list[datetime]:
    """Ejecuciones que ya deberian haber ocurrido dentro de la ventana."""
    desde = ahora - timedelta(hours=horas)
    slot = ahora.replace(minute=MINUTO_CRON, second=0, microsecond=0)
    if slot > ahora:
        slot -= timedelta(hours=1)

    esperados: list[datetime] = []
    while slot >= desde:
        esperados.append(slot)
        slot -= timedelta(hours=1)
    return list(reversed(esperados))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba si el vigilante se esta ejecutando en GitHub Actions."
    )
    parser.add_argument("--horas", type=int, default=24, help="Ventana a revisar.")
    parser.add_argument(
        "--detalle",
        action="store_true",
        help="Descarga el log de cada pasada para decir que encontro. Mas lento.",
    )
    args = parser.parse_args(argv)

    try:
        runs = listar_runs(min(args.horas * 2 + 20, 200))
    except GhError as exc:
        print(f"❌ {exc}")
        return 1

    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=args.horas)

    por_slot: dict[datetime, dict] = {}
    for run in runs:
        if run["event"] != "schedule":
            continue
        inicio = datetime.fromisoformat(run["startedAt"].replace("Z", "+00:00"))
        if inicio < desde:
            continue
        slot = slot_de(inicio)
        por_slot.setdefault(slot, {"run": run, "retraso": inicio - slot})

    esperados = slots_esperados(ahora, args.horas)
    huecos = [s for s in esperados if s not in por_slot]

    print(f"Ventana: ultimas {args.horas} h  (ahora {ahora.astimezone():%H:%M} local)")
    print(f"Esperadas: {len(esperados)}   ejecutadas: {len(esperados) - len(huecos)}")
    print()

    for slot in esperados:
        hora = slot.astimezone().strftime("%d/%m %H:%M")
        entrada = por_slot.get(slot)
        if entrada is None:
            print(f"  {hora}   ✗   NO SE EJECUTO")
            continue
        run = entrada["run"]
        marca = SIMBOLO.get(run["conclusion"], "?")
        retraso = int(entrada["retraso"].total_seconds() // 60)
        linea = f"  {hora}   {marca}   {run['conclusion'] or run['status']}"
        if retraso:
            linea += f", {retraso} min tarde"
        if args.detalle:
            linea += f"  ·  {resumen_del_log(run['databaseId'])}"
        print(linea)

    print()
    if not esperados:
        print("Aun no ha tocado ninguna ejecucion programada en esta ventana.")
    elif not huecos:
        print("✅ No falta ninguna. Si no te ha llegado nada a Discord, es que no")
        print("   habia chollos por debajo de tus precios.")
    else:
        print(f"⚠️  Faltan {len(huecos)} de {len(esperados)}. GitHub descarta")
        print("   ejecuciones programadas cuando va cargado; si el hueco es grande,")
        print("   prueba a mover el minuto del cron en .github/workflows/monitor.yml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
