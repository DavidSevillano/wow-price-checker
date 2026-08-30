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
function time() return AHORA end
function UnitName() return PERSONAJE end
function GetRealmName() return REINO end
function GetDetailedItemLevelInfo() return ILVL end

SlashCmdList = {}

C_Timer = { After = function(_, fn) fn() end }

C_AuctionHouse = {
    GetNumOwnedAuctions = function() return #SUBASTAS end,
    GetOwnedAuctionInfo = function(i) return SUBASTAS[i] end,
    -- En el juego la consulta es asincrona y su respuesta dispara el evento.
    QueryOwnedAuctions = function() DISPARAR("OWNED_AUCTIONS_UPDATED") end,
}

function DISPARAR(evento, arg1) eventos.OnEvent(nil, evento, arg1) end
"""


def runtime(personaje="Pepe", reino="Sanguino", ilvl=311, subastas=None):
    """Un Lua con el addon cargado y las APIs de WoW simuladas."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().PERSONAJE = personaje
    lua.globals().REINO = reino
    lua.globals().ILVL = ilvl
    lua.globals().AHORA = 1756500000
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
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" in mensajes


def test_al_abrir_nunca_recuerda_lo_del_reload():
    """La casa de subastas entrega tus subastas por partes: a mitad de la
    entrega lo guardado no coincide con el disco, y el aviso saltaria siempre.
    Ademas, al abrir todavia no has hecho nada."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "registradas" in mensajes
    assert "/reload" not in mensajes


def test_no_avisa_cuando_no_ha_cambiado_nada():
    lua = runtime(subastas=[subasta()])
    # Primera pasada: se recoge y se "guarda a disco".
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    # Se simula el arranque siguiente con eso ya en disco.
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" not in mensajes


def test_no_avisa_cuando_solo_ha_pasado_el_tiempo():
    """El volcado lleva la hora de exportacion, que cambia en cada lectura. Si
    se compara eso, el aviso de 'sin guardar a disco' sale siempre."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().mensajes = lua.table_from([])

    # Vuelves a entrar mas tarde, con las mismas subastas.
    lua.globals().AHORA = 1756599999
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" not in mensajes


def test_si_avisa_cuando_de_verdad_hay_algo_nuevo():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SUBASTAS = lua.table_from([subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" in mensajes


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


def test_el_comando_dice_la_version_y_lo_guardado():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SlashCmdList["WOWALERTS"]()

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "WoW Alerts v" in mensajes
    assert "tengo guardadas" in mensajes


def test_postear_sin_cerrar_la_casa_actualiza():
    """Antes habia que cerrar y volver a abrir la casa de subastas: el addon
    solo miraba al abrirla, asi que se quedaba con la foto de ese momento."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 1

    lua.globals().SUBASTAS = lua.table_from([subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_cancelar_sin_cerrar_la_casa_actualiza():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)

    lua.globals().SUBASTAS = lua.table_from([subasta(auction_id=2)])
    lua.globals().DISPARAR("AUCTION_CANCELED")

    subastas = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [2]


def test_una_tanda_de_posteos_no_dispara_una_consulta_por_cada_uno():
    lua = runtime(subastas=[subasta()])
    # El temporizador deja de ejecutar al momento: se cuenta cuantos se piden,
    # que es lo que mide si las peticiones seguidas se agrupan.
    lua.execute("""
        PENDIENTES = 0
        C_Timer = { After = function() PENDIENTES = PENDIENTES + 1 end }
    """)

    for _ in range(5):
        lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    # Cinco posteos seguidos, un unico temporizador pendiente.
    assert lua.globals().PENDIENTES == 1


def test_el_comando_no_cuenta_antes_de_que_llegue_la_respuesta():
    """La consulta es asincrona: contar en la misma linea que se pide daba cero
    y hacia creer que el addon no leia nada."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SlashCmdList["WOWALERTS"]()

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "tengo guardadas" in mensajes
    assert "no puedo leer nada" not in mensajes


def test_al_abrir_la_casa_sale_un_mensaje():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "2 subasta(s) tuyas registradas" in mensajes


def test_al_cerrar_la_casa_sale_un_mensaje_con_lo_guardado():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    # Con la casa cerrada el juego ya no devuelve nada, pero lo guardado sigue.
    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "2 subasta(s) tuyas registradas" in mensajes


def test_postear_y_cancelar_no_llena_el_chat():
    """El resumen es solo al abrir y al cerrar: mientras trabajas, silencio."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    for i in range(2, 12):
        lua.globals().SUBASTAS = lua.table_from([subasta(auction_id=j) for j in range(1, i + 1)])
        lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    assert " ".join(lua.globals().mensajes.values()) == ""
    # Pero si que se ha ido guardando por el camino.
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 11
