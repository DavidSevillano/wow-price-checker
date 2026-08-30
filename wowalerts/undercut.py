"""Deteccion de undercuts sobre tus propias subastas.

La regla vive aqui y es pura: recibe las subastas de un reino ya descargadas y
tus publicaciones ya leidas, y devuelve quien te ha adelantado. Igual que
`scanner.find_deals`, eso permite probarla entera sin tocar la red.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from .config import COPPER_PER_GOLD
from .ilvl import resolve_ilvl
from .misubastas import MyAuction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Undercut:
    """Una subasta tuya con al menos un rival a su precio o por debajo."""

    mine: MyAuction
    rival_auction_id: int
    rival_price_copper: int
    rival_ilvl_confirmed: bool
    rivals_ahead: int
    # El reino conectado donde se ha visto. Lo necesita la memoria de avisos,
    # porque los ids de subasta solo son unicos dentro de su reino.
    realm_id: int = 0

    @property
    def my_price_gold(self) -> int:
        return self.mine.buyout_copper // COPPER_PER_GOLD

    @property
    def rival_price_gold(self) -> int:
        return self.rival_price_copper // COPPER_PER_GOLD

    @property
    def gap_copper(self) -> int:
        """Cuanto mas barato esta el rival. Cero si te ha igualado."""
        return self.mine.buyout_copper - self.rival_price_copper

    @property
    def gap_gold(self) -> int:
        return self.gap_copper // COPPER_PER_GOLD

    @property
    def tied(self) -> bool:
        return self.gap_copper == 0


def find_undercuts(
    auctions: Sequence[Mapping],
    my_auctions: Sequence[MyAuction],
    bonus_ilvl_map: Mapping[int, int],
    realm_id: int = 0,
) -> list[Undercut]:
    """Devuelve una entrada por cada subasta tuya que alguien haya adelantado.

    Las comparaciones van siempre en cobre: convertir a oro antes de comparar
    redondearia hacia abajo y colaria como empate un precio que no lo es.
    """
    if not my_auctions:
        return []

    mias_por_id = {m.auction_id: m for m in my_auctions}
    objetos_vigilados = {m.item_id for m in my_auctions}

    # Solo interesa saber si siguen vivas las tuyas, no las 30.000 del reino.
    vivas: set[int] = set()
    por_ilvl: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    sin_ilvl: dict[int, list[tuple[int, int]]] = defaultdict(list)

    for auction in auctions:
        auction_id = auction.get("id")
        if not isinstance(auction_id, int) or isinstance(auction_id, bool):
            continue

        if auction_id in mias_por_id:
            vivas.add(auction_id)
            continue

        item_obj = auction.get("item") or {}
        item_id = item_obj.get("id")
        if item_id not in objetos_vigilados:
            continue

        # Sin compra directa no compite en precio con la tuya.
        price = auction.get("buyout")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            continue

        ilvl = resolve_ilvl(item_obj, bonus_ilvl_map)
        if ilvl.value is None:
            sin_ilvl[item_id].append((auction_id, price))
        else:
            por_ilvl[(item_id, ilvl.value)].append((auction_id, price))

    undercuts: list[Undercut] = []

    for mine in my_auctions:
        if mine.auction_id not in vivas:
            log.debug(
                "Tu subasta %s de %s ya no esta en la casa de subastas: "
                "vendida, caducada o cancelada.",
                mine.auction_id,
                mine.item_name,
            )
            continue

        candidatos = [
            (aid, precio, True)
            for aid, precio in por_ilvl.get((mine.item_id, mine.ilvl), [])
        ]
        # Un rival cuyo ilvl no se puede deducir podria ser del tuyo, asi que
        # entra como candidato marcado para que el aviso lo advierta.
        candidatos += [
            (aid, precio, False) for aid, precio in sin_ilvl.get(mine.item_id, [])
        ]

        delante = [c for c in candidatos if c[1] <= mine.buyout_copper]
        if not delante:
            continue

        # El mas barato primero; a igualdad de precio, el de ilvl confirmado,
        # que es el dato mas util para decidir a que precio repostear.
        delante.sort(key=lambda c: (c[1], not c[2]))
        auction_id, precio, confirmado = delante[0]

        undercuts.append(
            Undercut(
                mine=mine,
                rival_auction_id=auction_id,
                rival_price_copper=precio,
                rival_ilvl_confirmed=confirmado,
                rivals_ahead=len(delante),
                realm_id=realm_id,
            )
        )

    undercuts.sort(key=lambda u: u.gap_copper, reverse=True)
    return undercuts
