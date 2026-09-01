"""El panel de estado: un unico mensaje de Discord que se reescribe cada hora.

Los avisos cuentan lo que ha cambiado; el panel cuenta como estas. Fijado en el
canal, es lo que miras desde el movil para ver de un vistazo que personajes
tienen algo que atender, sin rebuscar entre los avisos sueltos.

La construccion del mensaje es una funcion pura, para poder comprobar el
formato sin enviar nada.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from .misubastas import MyAuction
from .undercut import Undercut

# Limite de Discord para la descripcion de un embed.
MAX_DESCRIPCION = 4096

COLOR_TODO_BIEN = 0x2ECC71   # verde: nadie te ha adelantado
COLOR_HAY_TRABAJO = 0xC0392B  # rojo: toca repostear algo


def _quien(subasta: MyAuction) -> str:
    if subasta.account is None:
        return subasta.character
    return f"{subasta.character} · WoW {subasta.account}"


def _linea(undercut: Undercut) -> str:
    """Una subasta adelantada, con el precio que hay que batir."""
    from .notifier import format_gold

    if undercut.tied:
        return (
            f"⚠️ {undercut.mine.item_name} — te igualan a "
            f"{format_gold(undercut.rival_price_gold)} g"
        )
    return (
        f"⚠️ {undercut.mine.item_name} — ~~{format_gold(undercut.my_price_gold)}~~ "
        f"**{format_gold(undercut.rival_price_gold)} g**"
    )


def build_panel(
    mis_subastas: Sequence[MyAuction],
    undercuts: Sequence[Undercut],
    actualizado: datetime | None = None,
    caducados: Sequence[str] = (),
) -> dict[str, Any]:
    """El mensaje del panel, listo para enviar o para reescribir el existente."""
    if not mis_subastas:
        return {
            "embeds": [
                {
                    "title": "📊 Tus subastas",
                    "description": (
                        "No conozco ninguna subasta tuya de los objetos "
                        "vigilados. Entra al juego, abre la Casa de Subastas y "
                        "haz `/reload`."
                    ),
                    "color": COLOR_TODO_BIEN,
                }
            ]
        }

    adelantadas: dict[int, Undercut] = {u.mine.auction_id: u for u in undercuts}

    # Un grupo por personaje, ordenados: primero los que tienen trabajo.
    grupos: dict[str, list[MyAuction]] = {}
    for subasta in mis_subastas:
        grupos.setdefault(_quien(subasta), []).append(subasta)

    def prioridad(entrada):
        _, suyas = entrada
        pendientes = sum(1 for s in suyas if s.auction_id in adelantadas)
        return (-pendientes, -len(suyas))

    bloques: list[str] = []
    for quien, suyas in sorted(grupos.items(), key=prioridad):
        pendientes = [adelantadas[s.auction_id] for s in suyas if s.auction_id in adelantadas]
        cuantas = f"{len(suyas)} vigilada{'s' if len(suyas) != 1 else ''}"

        if pendientes:
            cabecera = (
                f"**{quien}** — {cuantas}, "
                f"{len(pendientes)} adelantada{'s' if len(pendientes) != 1 else ''}"
            )
            cuerpo = [cabecera] + [_linea(u) for u in pendientes]
        else:
            cuerpo = [f"**{quien}** — {cuantas}, todas primeras ✅"]

        bloques.append("\n".join(cuerpo))

    descripcion, omitidos = _recortar(bloques)

    total = len(mis_subastas)
    if adelantadas:
        resumen = f"{len(adelantadas)} de tus {total} subastas vigiladas necesitan atencion."
    else:
        resumen = f"Tus {total} subastas vigiladas van primeras. Nada que hacer."

    if omitidos:
        descripcion += f"\n\n_y {omitidos} personaje(s) mas sin novedad_"

    if caducados:
        # Ninguna subasta que el addon conoce de estos personajes sigue viva, o
        # sea que sus datos son de antes de que las repostearas. Contra ids
        # muertos no se detecta nada: ni undercuts ni ventas, y en silencio.
        quienes = ", ".join(sorted(caducados)[:12])
        if len(caducados) > 12:
            quienes += f" y {len(caducados) - 12} mas"
        descripcion += (
            f"\n\n⚠️ **Datos caducados en {len(caducados)} personaje(s)**: "
            f"{quienes}.\nNinguna de sus subastas conocidas sigue viva, asi que "
            "no puedo vigilarlos. Entra con ellos, abre la Casa de Subastas y "
            "haz `/reload`."
        )

    embed: dict[str, Any] = {
        "title": "📊 Tus subastas",
        "description": f"{resumen}\n\n{descripcion}",
        "color": COLOR_HAY_TRABAJO if adelantadas else COLOR_TODO_BIEN,
    }
    if actualizado:
        # Discord lo pinta en la zona horaria de quien lo lee.
        embed["timestamp"] = actualizado.isoformat()
        embed["footer"] = {"text": "datos del volcado de Blizzard"}

    return {"embeds": [embed]}


def _recortar(bloques: list[str]) -> tuple[str, int]:
    """Los bloques que caben en el mensaje, y cuantos se han quedado fuera.

    Los que tienen trabajo van primero, asi que lo que se recorta por abajo es
    siempre lo que no necesita atencion.
    """
    # Margen para el resumen de arriba y la nota de los omitidos.
    presupuesto = MAX_DESCRIPCION - 300
    dentro: list[str] = []
    largo = 0

    for bloque in bloques:
        if dentro and largo + len(bloque) + 2 > presupuesto:
            break
        dentro.append(bloque)
        largo += len(bloque) + 2

    return "\n\n".join(dentro), len(bloques) - len(dentro)
