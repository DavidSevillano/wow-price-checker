"""El addon de WoW, ejecutado fuera del juego.

Las APIs de WoW se sustituyen por dobles, asi que se puede comprobar lo unico
del addon que de verdad puede fallar en silencio: que el JSON que escribe sea
JSON valido y que los datos que mete sean los correctos. Lo demas (que los
eventos lleguen) solo se puede ver dentro del juego.

Necesita `lupa`, que va en requirements-dev.txt. Sin el, los tests se saltan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport" / "WowAlertsExport.lua"

# Un enlace de objeto real: 3 bonus ids (6652, 7981, 1498) en las posiciones
# 14, 15 y 16, que es donde el addon los busca.
LINK = "|cffa335ee|Hitem:200000::::::::80:250::14:3:6652:7981:1498:::|h[Greaves of the Noxious Depths]|h|r"

DOBLES = """
-- Dobles de las APIs de WoW que usa el addon.
local eventos = {}
mensajes = {}

function CreateFrame()
    return {
        RegisterEvent = function() end,
        SetScript = function(self, _, handler) eventos.OnEvent = handler end,
    }
end

function print(texto) mensajes[#mensajes + 1] = texto end
function time() return 1756500000 end
function UnitName() return PERSONAJE end
function GetRealmName() return REINO end
function GetDetailedItemLevelInfo() return ILVL end

SlashCmdList = {}

C_AuctionHouse = {
    GetNumOwnedAuctions = function() return #SUBASTAS end,
    GetOwnedAuctionInfo = function(i) return SUBASTAS[i] end,
    QueryOwnedAuctions = function() end,
}

function DISPARAR(evento, arg1) eventos.OnEvent(nil, evento, arg1) end
"""


def runtime(personaje="Pepe", reino="Sanguino", ilvl=311, subastas=None):
    """Un Lua con el addon cargado y las APIs de WoW simuladas."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().PERSONAJE = personaje
    lua.globals().REINO = reino
    lua.globals().ILVL = ilvl
    lua.execute(DOBLES)

    lua.globals().SUBASTAS = lua.table_from(subastas or [])
    lua.execute(ADDON.read_text(encoding="utf-8"))
    return lua


def subasta(auction_id=1, item_id=200000, buyout=90_000_000, quantity=1, link=LINK):
    return {
        "auctionID": auction_id,
        "itemKey": {"itemID": item_id, "itemLevel": 311},
        "itemLink": link,
        "buyoutAmount": buyout,
        "quantity": quantity,
    }


def recoger(lua):
    """Abre la casa de subastas y deja que el addon recoja lo que hay."""
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")


def volcado(lua) -> dict:
    """El payload que el addon dejaria en SavedVariables, ya parseado."""
    return json.loads(lua.globals().WowAlertsExportDB.payload)


def test_el_payload_es_json_valido():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    assert volcado(lua)["version"] == 1


def test_exporta_los_datos_de_la_subasta():
    lua = runtime(subastas=[subasta()])
    recoger(lua)

    entrada = volcado(lua)["personajes"]["Sanguino-Pepe"]
    assert entrada["character"] == "Pepe"
    assert entrada["realm"] == "Sanguino"
    assert entrada["auctions"] == [
        {
            "auctionID": 1,
            "itemID": 200000,
            "itemName": "Greaves of the Noxious Depths",
            "ilvl": 311,
            "bonusIDs": [6652, 7981, 1498],
            "buyout": 90000000,
            "quantity": 1,
        }
    ]


def test_ignora_las_subastas_sin_compra_directa():
    lua = runtime(subastas=[subasta(buyout=0), subasta(auction_id=2)])
    recoger(lua)

    subastas = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [2]


def test_un_enlace_sin_bonus_ids_no_rompe():
    sin_bonus = "|cffffffff|Hitem:200000::::::::80:250::14:0:::|h[Cosa]|h|r"
    lua = runtime(subastas=[subasta(link=sin_bonus)])
    recoger(lua)

    entrada = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"][0]
    assert entrada["bonusIDs"] == []
    assert entrada["itemName"] == "Cosa"


def test_sin_subastas_el_personaje_sale_igualmente_con_lista_vacia():
    lua = runtime(subastas=[])
    recoger(lua)
    assert volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"] == []


def test_los_nombres_con_comillas_no_rompen_el_json():
    lua = runtime(personaje='Pe"pe', subastas=[subasta()])
    recoger(lua)
    assert volcado(lua)["personajes"]['Sanguino-Pe"pe']["character"] == 'Pe"pe'


def test_avisa_de_que_falta_volcar_a_disco():
    lua = runtime(subastas=[subasta()])
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    recoger(lua)

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" in mensajes


def test_no_avisa_cuando_no_ha_cambiado_nada():
    lua = runtime(subastas=[subasta()])
    # Primera pasada: se recoge y se "guarda a disco".
    recoger(lua)
    lua.execute("VOLCADO = WowAlertsExportDB.payload")
    lua.globals().mensajes = lua.table_from([])

    # Se simula un reinicio con ese payload ya en disco.
    lua.execute("WowAlertsExportDB.payload = VOLCADO")
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    recoger(lua)

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" not in mensajes


def test_leer_cero_no_borra_lo_ya_recogido():
    """La regresion que costo un viaje al juego: con la casa de subastas
    cerrada el juego devuelve cero subastas, y eso machacaba las buenas."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2

    # Cierras la casa de subastas: el juego ya no sabe que tienes puesto.
    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_el_comando_funciona_sin_haber_visto_abrir_la_casa():
    """La segunda regresion: un /reload con la casa de subastas ya abierta.

    El evento de apertura no vuelve a dispararse, asi que el addon no puede
    fiarse de haberlo visto para saber si puede leer.
    """
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().SlashCmdList["WOWALERTS"]()

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2
    mensajes = " ".join(lua.globals().mensajes.values())
    assert "2 subasta(s) registradas" in mensajes


def test_el_comando_sin_poder_leer_dice_lo_que_conserva():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().SlashCmdList["WOWALERTS"]()

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "conservo las 2" in mensajes
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2
