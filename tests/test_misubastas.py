"""Lectura de los volcados del addon."""

import json

import pytest

from wowalerts.misubastas import (
    MisSubastasError,
    MyAuction,
    cuenta_de_ruta,
    extraer_payload,
    fusionar_payloads,
    leer_de_wow,
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
        # Blizzard borra el apostrofo, no lo convierte en guion.
        ("Zul'jin", "zuljin"),
        ("Blade's Edge", "blades-edge"),
    ],
)
def test_slug_del_reino(nombre, esperado):
    assert slugify_realm(nombre) == esperado


# -- Numero de cuenta de WoW ------------------------------------------------


@pytest.mark.parametrize(
    "ruta,esperado",
    [
        (r"D:\WoW\_retail_\WTF\Account\403840080#2\SavedVariables\W.lua", 2),
        (r"D:\WoW\_retail_\WTF\Account\403840080#1\SavedVariables\W.lua", 1),
        ("/wow/WTF/Account/403840080#3/SavedVariables/W.lua", 3),
        # Una cuenta sin sufijo no dice de cual se trata: mejor no inventarlo.
        ("/wow/WTF/Account/MICUENTA/SavedVariables/W.lua", None),
        ("/wow/WTF/Account/RARO#X/SavedVariables/W.lua", None),
    ],
)
def test_cuenta_deducida_de_la_carpeta(ruta, esperado):
    assert cuenta_de_ruta(ruta) == esperado


def test_la_cuenta_se_deduce_igual_con_barras_de_cualquier_tipo():
    """CI lo encontro: Path.parts depende del sistema, y en Linux una ruta de
    Windows entera es un solo componente."""
    assert cuenta_de_ruta("D:/Juegos/WoW/WTF/Account/403840080#2/SavedVariables/W.lua") == 2
    assert cuenta_de_ruta(r"D:\Juegos\WoW\WTF\Account\403840080#2\SavedVariables\W.lua") == 2
    assert cuenta_de_ruta("403840080#2") == 2


def test_una_maquina_sin_volcado_todavia_no_es_un_error(tmp_path):
    """En la Steam Deck recien montada no hay nada hasta que juegas alli. Si
    eso fuera un error, la sincronizacion programada fallaria cada cuarto de
    hora sin motivo."""
    (tmp_path / "WTF" / "Account").mkdir(parents=True)
    assert leer_de_wow(tmp_path) is None


# -- Cancelaciones ----------------------------------------------------------

from wowalerts.misubastas import canceladas_de_payload, leer_canceladas


def test_las_cancelaciones_salen_del_payload():
    payload = {"canceladas": {"12345": 1756000000, "999": 1756000001}}
    assert canceladas_de_payload(payload) == {12345, 999}


def test_un_payload_sin_cancelaciones_no_falla():
    assert canceladas_de_payload({"personajes": {}}) == set()


def test_una_lista_vacia_de_lua_se_acepta():
    # El codificador del addon escribe [] cuando la tabla esta vacia.
    assert canceladas_de_payload({"canceladas": []}) == set()


def test_las_claves_que_no_son_numeros_se_ignoran():
    assert canceladas_de_payload({"canceladas": {"ab": 1, "7": 2}}) == {7}


def test_las_cancelaciones_se_leen_de_la_carpeta(tmp_path):
    (tmp_path / "pc.json").write_text(
        '{"version": 1, "auctions": [], "canceladas": [1, 2]}', encoding="utf-8"
    )
    (tmp_path / "deck.json").write_text(
        '{"version": 1, "auctions": [], "canceladas": [3]}', encoding="utf-8"
    )
    assert leer_canceladas(tmp_path) == {1, 2, 3}


def test_una_carpeta_sin_volcados_no_tiene_cancelaciones(tmp_path):
    assert leer_canceladas(tmp_path) == set()
