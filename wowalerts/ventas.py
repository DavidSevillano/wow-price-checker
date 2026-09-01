"""Deteccion de ventas de tus propias subastas.

La API de Blizzard no publica ventas: solo una foto por hora de lo que sigue
vivo. Una subasta tuya que desaparece pudo venderse, caducar o cancelarse, y
desde fuera las tres se ven igual.

Aqui se separa la primera de las otras dos con una sola idea: de cada subasta
se guarda la fecha mas temprana en la que PODRIA caducar. Si desaparece antes
de esa fecha, es imposible que haya caducado.

La regla es pura, como scanner.find_deals y undercut.find_undercuts: recibe el
volcado ya descargado y devuelve las ventas, sin tocar red ni disco.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import AbstractSet, Mapping, Sequence

from .config import COPPER_PER_GOLD
from .misubastas import MyAuction

log = logging.getLogger(__name__)

# Vida minima que garantiza cada tramo de Blizzard. SHORT no garantiza nada:
# "menos de 30 minutos" incluye "un segundo".
TIEMPO_MINIMO_RESTANTE = {
    "VERY_LONG": timedelta(hours=12),
    "LONG": timedelta(hours=2),
    "MEDIUM": timedelta(minutes=30),
    "SHORT": timedelta(0),
}


@dataclass(frozen=True)
class UltimoVolcado:
    """La foto anterior de un reino: cuando se leyo y hasta que id llegaba.

    El id maximo es lo que permite afirmar que una subasta acaba de nacer: los
    ids crecen con el tiempo dentro de un reino, asi que uno mayor que todos los
    de la foto anterior se publico despues de ella.
    """

    dump_at: datetime
    max_auction_id: int


@dataclass(frozen=True)
class SubastaVigilada:
    """Una subasta tuya en seguimiento, con lo justo para anunciar su venta.

    Guarda una copia de los datos del objeto a proposito. Cuando vendes y luego
    haces /reload, el volcado del addon deja de mencionarla, y eso puede pasar
    antes de la pasada siguiente: sin esta copia, esa venta no se anunciaria
    nunca.
    """

    auction_id: int
    item_id: int
    item_name: str
    # Hace falta en el aviso: el mismo objeto se vende a 292, 295, 298 y 305, y
    # sin el ilvl no se sabe cual de todas se ha ido.
    ilvl: int
    buyout_copper: int
    quantity: int
    character: str
    realm: str
    account: int | None
    # La fecha mas temprana en la que esta subasta podria caducar. Es una
    # garantia acumulada: solo sube, nunca baja.
    no_caduca_antes_de: datetime
    # Hora del ultimo volcado en el que se vio viva. Sirve para olvidarla si el
    # reino deja de escanearse.
    visto_at: datetime
    # Si la ultima vez que se vio viva alguien la habia adelantado. Cuando una
    # subasta adelantada desaparece, lo que ha pasado es que has ido a
    # repostearla: el aviso de undercut existe justamente para eso.
    adelantada: bool = False
    # Hora del volcado en el que se la vio faltar por primera vez. Mientras vale
    # None sigue viva. Una subasta que falta no se canta como vendida hasta la
    # pasada siguiente, para dar tiempo a que llegue del juego la noticia de que
    # la cancelaste tu: el volcado de Blizzard se entera de tus cancelaciones
    # antes que el addon, que solo escribe a disco al hacer /reload.
    desaparecida_at: datetime | None = None


@dataclass(frozen=True)
class Venta:
    """Una subasta tuya que ha desaparecido antes de poder caducar."""

    subasta: SubastaVigilada
    realm_id: int
    detectada_at: datetime
    ah_cut_pct: int = 5

    @property
    def neto_copper(self) -> int:
        """Lo que llega al buzon: el precio menos la comision de la casa.

        El descuento va en cobre y antes de pasar a oro, porque redondear a oro
        primero perderia la parte que se queda la casa en los precios bajos.
        """
        return self.subasta.buyout_copper * (100 - self.ah_cut_pct) // 100

    @property
    def neto_gold(self) -> int:
        return self.neto_copper // COPPER_PER_GOLD



def cota_por_time_left(time_left: str, dump_at: datetime) -> datetime:
    """Hasta cuando garantiza vivir una subasta vista en ese tramo.

    Un tramo que no reconozcamos no garantiza nada: si Blizzard inventa uno
    nuevo, callarse es mejor que afirmar de mas.
    """
    return dump_at + TIEMPO_MINIMO_RESTANTE.get(
        str(time_left).upper(), timedelta(0)
    )


def _vigilada_de(mia: MyAuction, dump_at: datetime) -> SubastaVigilada:
    """La copia inicial de una subasta tuya que se empieza a seguir."""
    return SubastaVigilada(
        auction_id=mia.auction_id,
        item_id=mia.item_id,
        item_name=mia.item_name,
        ilvl=mia.ilvl,
        buyout_copper=mia.buyout_copper,
        quantity=mia.quantity,
        character=mia.character,
        realm=mia.realm,
        account=mia.account,
        no_caduca_antes_de=dump_at,
        visto_at=dump_at,
    )


def revisar_reino(
    seguidas: Mapping[int, SubastaVigilada],
    mis_subastas: Sequence[MyAuction],
    auctions: Sequence[Mapping],
    realm_id: int,
    dump_at: datetime,
    anterior: UltimoVolcado | None,
    listing_hours: int = 12,
    ah_cut_pct: int = 5,
    adelantadas: AbstractSet[int] = frozenset(),
    canceladas: AbstractSet[int] = frozenset(),
    decidir: bool = True,
) -> tuple[list[Venta], dict[int, SubastaVigilada], UltimoVolcado]:
    """Las ventas de este reino, el seguimiento actualizado y su foto nueva.

    `anterior` es la foto del ultimo volcado de ESTE reino leido con exito. Vale
    None cuando es la primera vez o cuando el reino fallo, y entonces no se
    aplica la cota de nacimiento: sin saber que habia antes, no se puede
    afirmar que una subasta acabe de publicarse.

    `adelantadas` son las subastas tuyas que alguien esta adelantando ahora
    mismo, y `canceladas` las que el addon ha visto que retiraste tu: ni unas ni
    otras son ventas.

    Con `decidir` a False (la ventana de silencio) se sigue el rastro igual,
    pero no se cierra ningun caso: lo que falte se queda pendiente y se resuelve
    al despertar, con la hora en la que desaparecio de verdad.
    """
    mias_por_id = {m.auction_id: m for m in mis_subastas}

    # Una sola pasada por el volcado: de las 30.000 subastas del reino solo
    # interesan las tuyas, pero el id maximo se calcula sobre todas, que es lo
    # que hace fiable la cota de nacimiento.
    vivas: dict[int, str] = {}
    max_auction_id = 0
    for auction in auctions:
        auction_id = auction.get("id")
        if not isinstance(auction_id, int) or isinstance(auction_id, bool):
            continue
        max_auction_id = max(max_auction_id, auction_id)
        if auction_id in mias_por_id or auction_id in seguidas:
            vivas[auction_id] = str(auction.get("time_left", ""))

    nuevas: dict[int, SubastaVigilada] = {}
    for auction_id, time_left in vivas.items():
        previa = seguidas.get(auction_id)

        cotas = [cota_por_time_left(time_left, dump_at)]
        if previa is not None:
            cotas.append(previa.no_caduca_antes_de)
        if anterior is not None and auction_id > anterior.max_auction_id:
            # No estaba en la foto anterior: se publico despues de ella, asi que
            # su plazo entero cuenta desde entonces.
            cotas.append(anterior.dump_at + timedelta(hours=listing_hours))

        base = (
            previa
            if previa is not None
            else _vigilada_de(mias_por_id[auction_id], dump_at)
        )

        # Si el addon ya no la conoce no se puede recalcular su undercut, asi
        # que se conserva lo ultimo que se supo: callarse de mas es preferible a
        # inventarse una venta.
        adelantada = (
            auction_id in adelantadas
            if auction_id in mias_por_id
            else base.adelantada
        )

        nuevas[auction_id] = replace(
            base,
            no_caduca_antes_de=max(cotas),
            visto_at=dump_at,
            adelantada=adelantada,
            desaparecida_at=None,
        )

    ventas: list[Venta] = []
    for auction_id, vigilada in seguidas.items():
        if auction_id in vivas:
            continue

        if auction_id in canceladas:
            log.info(
                "↩️  %s de %s: la cancelaste tu, asi que no la cuento como venta.",
                vigilada.character,
                vigilada.item_name,
            )
            continue

        if vigilada.adelantada:
            # El aviso de undercut te manda a repostear, asi que una subasta
            # adelantada que desaparece la has cancelado tu. Sin esta guarda,
            # cada aviso de undercut fabricaba una venta falsa a la hora
            # siguiente.
            log.info(
                "↩️  %s de %s: ha desaparecido, pero te la estaban adelantando. "
                "La doy por reposteada, no por vendida.",
                vigilada.character,
                vigilada.item_name,
            )
            continue

        if not decidir:
            # En silencio no se cierra nada: se anota la desaparicion si es la
            # primera vez y se deja para cuando toque avisar.
            nuevas[auction_id] = (
                vigilada
                if vigilada.desaparecida_at is not None
                else replace(vigilada, desaparecida_at=dump_at)
            )
            continue

        if vigilada.desaparecida_at is None:
            # Falta por primera vez: se espera una pasada. Blizzard se entera de
            # tus cancelaciones antes que el addon, que solo vuelca a disco al
            # hacer /reload, asi que cantar la venta ya seria adelantarse a la
            # unica fuente capaz de desmentirla.
            nuevas[auction_id] = replace(vigilada, desaparecida_at=dump_at)
            log.debug(
                "Tu subasta %s de %s ha desaparecido. Espero una pasada por si "
                "resulta que la cancelaste.",
                auction_id,
                vigilada.item_name,
            )
            continue

        # Segunda pasada seguida sin aparecer y sin noticia de cancelacion.
        # Se juzga con la hora en que se fue, no con la de ahora: si no, la
        # espera empujaria la subasta mas alla de su fecha de caducidad y se
        # perderian ventas buenas.
        if vigilada.desaparecida_at < vigilada.no_caduca_antes_de:
            ventas.append(
                Venta(
                    subasta=vigilada,
                    realm_id=realm_id,
                    detectada_at=vigilada.desaparecida_at,
                    ah_cut_pct=ah_cut_pct,
                )
            )
        else:
            log.debug(
                "Tu subasta %s de %s ya podia haber caducado cuando desaparecio "
                "(su plazo vencia a las %s): no la cuento como venta.",
                auction_id,
                vigilada.item_name,
                vigilada.no_caduca_antes_de,
            )

    ventas.sort(key=lambda v: v.neto_copper, reverse=True)
    return ventas, nuevas, UltimoVolcado(dump_at, max_auction_id)
