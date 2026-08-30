"""Lectura de los volcados del addon."""

import json

import pytest

from wowalerts.misubastas import (
    MisSubastasError,
    MyAuction,
    extraer_payload,
    fusionar_payloads,
    slugify_realm,
    subastas_de_payloads,
)


def lua_con(payload: dict) -> str:
    """Imita lo que WoW escribe en SavedVariables."""
    crudo = json.dumps(payload, ensure_ascii=False)
    escapado = crudo.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "\nWowAlertsExportDB = {\n"
        '\t["version"] = 1,\n'
        f'\t["payload"] = "{escapado}",\n'
        "}\n"
    )


def payload_con(**personajes) -> dict:
    return {"version": 1, "personajes": personajes}


def personaje(nombre="Pepe", reino="Sanguino", exportedAt=100, auctions=()):
    return {
        "character": nombre,
        "realm": reino,
        "exportedAt": exportedAt,
        "auctions": list(auctions),
    }


def subasta(auctionID=1, itemID=200000, ilvl=311, buyout=900000000, quantity=1):
    return {
        "auctionID": auctionID,
        "itemID": itemID,
        "itemName": "Greaves of the Noxious Depths",
        "ilvl": ilvl,
        "bonusIDs": [],
        "buyout": buyout,
        "quantity": quantity,
    }


def test_extrae_el_payload_de_un_volcado_normal():
    texto = lua_con(payload_con(**{"Sanguino-Pepe": personaje()}))
    assert json.loads(extraer_payload(texto))["version"] == 1


def test_extrae_payload_con_comillas_y_acentos():
    texto = lua_con(
        payload_con(**{"Sanguino-Ñoño": personaje(nombre='Ño"ño', reino="Sanguino")})
    )
    datos = json.loads(extraer_payload(texto))
    assert datos["personajes"]["Sanguino-Ñoño"]["character"] == 'Ño"ño'


def test_payload_ausente_da_error_claro():
    with pytest.raises(MisSubastasError, match="payload"):
        extraer_payload("WowAlertsExportDB = {}\n")


def test_cadena_sin_cerrar_da_error_claro():
    with pytest.raises(MisSubastasError, match="sin cerrar"):
        extraer_payload('["payload"] = "{\\"version\\":1')


def test_fusionar_se_queda_con_el_volcado_mas_reciente():
    viejo = payload_con(**{"Sanguino-Pepe": personaje(exportedAt=100)})
    nuevo = payload_con(
        **{"Sanguino-Pepe": personaje(exportedAt=200, auctions=[subasta()])}
    )
    fusion = fusionar_payloads([nuevo, viejo])
    assert fusion["Sanguino-Pepe"]["exportedAt"] == 200
    assert len(fusion["Sanguino-Pepe"]["auctions"]) == 1


def test_fusionar_conserva_personajes_de_cuentas_distintas():
    uno = payload_con(**{"Sanguino-Pepe": personaje()})
    otro = payload_con(**{"Dun Modr-Ana": personaje(nombre="Ana", reino="Dun Modr")})
    assert set(fusionar_payloads([uno, otro])) == {"Sanguino-Pepe", "Dun Modr-Ana"}


def test_convierte_a_myauction_con_su_personaje_y_reino():
    fusion = fusionar_payloads(
        [
            payload_con(
                **{
                    "Dun Modr-Ana": personaje(
                        nombre="Ana", reino="Dun Modr", auctions=[subasta()]
                    )
                }
            )
        ]
    )
    subastas = subastas_de_payloads(fusion)
    assert subastas == [
        MyAuction(
            auction_id=1,
            item_id=200000,
            item_name="Greaves of the Noxious Depths",
            ilvl=311,
            buyout_copper=900000000,
            quantity=1,
            character="Ana",
            realm="Dun Modr",
            realm_slug="dun-modr",
        )
    ]


def test_descarta_entradas_incompletas_sin_romper():
    fusion = fusionar_payloads(
        [
            payload_con(
                **{"Sanguino-Pepe": personaje(auctions=[{"auctionID": 5}, subasta()])}
            )
        ]
    )
    assert [s.auction_id for s in subastas_de_payloads(fusion)] == [1]


@pytest.mark.parametrize(
    "nombre,esperado",
    [
        ("Sanguino", "sanguino"),
        ("Dun Modr", "dun-modr"),
        ("Área 52", "area-52"),
        ("Los Errantes", "los-errantes"),
    ],
)
def test_slug_del_reino(nombre, esperado):
    assert slugify_realm(nombre) == esperado
