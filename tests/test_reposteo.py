"""El reposteo con una tecla, ejecutado fuera del juego.

Las APIs de WoW se sustituyen por dobles que apuntan cada llamada protegida
(cancelar, postear, confirmar, recoger correo). Lo que no se puede ver aqui --que
el juego acepte esas llamadas desde una tecla-- se comprueba a mano en la
Task 9 del plan.

Necesita `lupa`, que va en requirements-dev.txt. Sin el, los tests se saltan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

CARPETA = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport"
GREBAS = 271440

DOBLES = r"""
-- Dobles de las APIs de WoW que usan el exportador y el reposteo.
local manejadores = {}
mensajes = {}
LLAMADAS = {}    -- funciones protegidas, en el orden en que se llaman
BUSQUEDAS = {}   -- itemKeys pedidas a la casa y aun sin responder
BUSCADAS = 0     -- cuantas busquedas se han lanzado en total

local function apuntar(...) LLAMADAS[#LLAMADAS + 1] = { ... } end

-- Cualquier metodo de interfaz que no importe devuelve un objeto que tampoco
-- hace nada, para poder encadenar llamadas (CreateFontString():SetText()...).
local NULO
NULO = setmetatable({}, { __index = function() return function() return NULO end end })

function CreateFrame(_, nombre)
    local frame = setmetatable({}, { __index = function() return function() return NULO end end })
    frame.SetScript = function(self, script, fn)
        if script == "OnEvent" then manejadores[#manejadores + 1] = fn end
        rawset(self, "script_" .. script, fn)
    end
    if nombre then _G[nombre] = frame end
    return frame
end

function DISPARAR(evento, ...)
    for _, fn in ipairs(manejadores) do fn(nil, evento, ...) end
end

function print(texto) mensajes[#mensajes + 1] = texto end
function time() return AHORA end
RELOJ = 0
function GetTime() return RELOJ end
function UnitName() return PERSONAJE end
function GetRealmName() return REINO end
-- Los enlaces de prueba llevan el ilvl escrito: "[Grebas]ilvl311".
function GetDetailedItemLevelInfo(enlace)
    return tonumber(tostring(enlace or ""):match("ilvl(%d+)"))
end

SlashCmdList = {}
C_Timer = {
    After = function(_, fn) fn() end,
    NewTicker = function() return { Cancel = function() end } end,
}

CASA_ABIERTA = false
AuctionHouseFrame = { IsShown = function() return CASA_ABIERTA end }
BUZON_ABIERTO = false
MailFrame = { IsShown = function() return BUZON_ABIERTO end }

Enum = { AuctionHouseSortOrder = { Price = 0 } }

local function clave(k)
    return k.itemID .. ":" .. (k.itemLevel or 0) .. ":" .. (k.itemSuffix or 0)
end

SUBASTAS = {}
RESULTADOS = {}
SISTEMA_LISTO = true
NECESITA_CONFIRMAR = false

C_AuctionHouse = {
    GetNumOwnedAuctions = function() return #SUBASTAS end,
    GetOwnedAuctionInfo = function(i) return SUBASTAS[i] end,
    QueryOwnedAuctions = function() DISPARAR("OWNED_AUCTIONS_UPDATED") end,
    IsThrottledMessageSystemReady = function() return SISTEMA_LISTO end,
    SendSearchQuery = function(itemKey)
        BUSCADAS = BUSCADAS + 1
        BUSQUEDAS[#BUSQUEDAS + 1] = itemKey
    end,
    GetNumItemSearchResults = function(k) return #(RESULTADOS[clave(k)] or {}) end,
    GetItemSearchResultInfo = function(k, i) return (RESULTADOS[clave(k)] or {})[i] end,
    CancelAuction = function(id) apuntar("CancelAuction", id) end,
    PostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("PostItem", loc.bag, loc.slot, duracion, cantidad, precio)
        -- Como el juego: el objeto queda bloqueado mientras se publica.
        local hueco = BOLSA[loc.bag .. ":" .. loc.slot]
        if hueco then hueco.isLocked = true end
        return NECESITA_CONFIRMAR
    end,
    ConfirmPostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("ConfirmPostItem", loc.bag, loc.slot, duracion, cantidad, precio)
    end,
}

-- Responde a la busqueda mas antigua, como haria el servidor.
function RESPONDER()
    local itemKey = table.remove(BUSQUEDAS, 1)
    DISPARAR("ITEM_SEARCH_RESULTS_UPDATED", itemKey)
end

AUCTION_REMOVED_MAIL_SUBJECT = "Auction cancelled: %s"
CORREO = {}   -- { asunto, nombre, itemID, enlace }
function GetInboxNumItems() return #CORREO, #CORREO end
function GetInboxHeaderInfo(i)
    local carta = CORREO[i]
    return nil, nil, "Auction House", carta.asunto, 0, 0, 30, carta.itemID and 1 or nil
end
function GetInboxItem(i)
    local carta = CORREO[i]
    return carta.nombre, carta.itemID, nil, 1, 4, true
end
function GetInboxItemLink(i) return CORREO[i].enlace end
function TakeInboxItem(i, adjunto) apuntar("TakeInboxItem", i, adjunto) end

NUM_BAG_SLOTS = 4
BOLSA = {}    -- ["bolsa:hueco"] = { itemID, hyperlink, isLocked }
C_Container = {
    GetContainerNumSlots = function() return 16 end,
    GetContainerItemInfo = function(bolsa, hueco) return BOLSA[bolsa .. ":" .. hueco] end,
}
ItemLocation = {}
function ItemLocation:CreateFromBagAndSlot(bolsa, hueco) return { bag = bolsa, slot = hueco } end
"""

VIGILADOS = """
WowAlertsVigilados = {
    objetos = { [271440] = "Greaves of the Noxious Depths" },
    personajes = { "Pepe", "Mbarval" },
    duracion = 1,
}
"""


def poner(lua, nombre, valor):
    lua.globals()[nombre] = lua.table_from(valor, recursive=True)


def runtime(subastas=None):
    """Un Lua con el exportador y el reposteo cargados, como en el juego."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.PERSONAJE = "Pepe"
    g.REINO = "Sanguino"
    g.AHORA = 1756500000
    lua.execute(DOBLES)
    lua.execute(VIGILADOS)
    poner(lua, "SUBASTAS", subastas or [])
    for nombre in ("WowAlertsExport.lua", "Reposteo.lua"):
        lua.execute((CARPETA / nombre).read_text(encoding="utf-8"))
    return lua


def a_python(valor):
    """Una tabla de Lua convertida en lista o diccionario de Python."""
    if lupa.lua_type(valor) != "table":
        return valor
    claves = list(valor.keys())
    if claves and all(isinstance(k, int) for k in claves) and sorted(claves) == list(
        range(1, len(claves) + 1)
    ):
        return [a_python(valor[k]) for k in sorted(claves)]
    if not claves:
        return []
    return {k: a_python(valor[k]) for k in claves}


def mia(auction_id, precio, item_id=GREBAS, ilvl=311, status=0):
    """Una subasta tuya, como la devuelve GetOwnedAuctionInfo."""
    return {
        "auctionID": auction_id,
        "itemKey": {"itemID": item_id, "itemLevel": ilvl},
        "itemLink": f"[Grebas]ilvl{ilvl}",
        "buyoutAmount": precio,
        "quantity": 1,
        "status": status,
    }


def en_venta(auction_id, precio, dueno="Extrano", propia=False, de_la_cuenta=False):
    """Una fila de resultados de busqueda, como la devuelve GetItemSearchResultInfo."""
    return {
        "auctionID": auction_id,
        "buyoutAmount": precio,
        "owners": [dueno],
        "containsOwnerItem": propia,
        "containsAccountItem": de_la_cuenta,
    }


def en_la_casa(lua, filas, item_id=GREBAS, ilvl=311):
    """Lo que devolvera la busqueda de ese objeto e ilvl."""
    poner(lua, "RESULTADOS", {f"{item_id}:{ilvl}:0": filas})


def abrir_casa(lua):
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")


def pulsar(lua):
    return lua.globals().WowAlertsReposteo.Siguiente()


def responder_todo(lua):
    while lua.eval("#BUSQUEDAS") > 0:
        lua.globals().RESPONDER()


def cola(lua):
    return a_python(lua.eval('((WowAlertsExportDB.reposteo or {})["Sanguino-Pepe"]) or {}'))


def llamadas(lua):
    return [tuple(c) for c in a_python(lua.globals().LLAMADAS)]


# -- La regla del rival --------------------------------------------------------


def _regla(lua, rival, mia_):
    return lua.globals().WowAlertsReposteo.vaPorDelante(
        lua.table_from(rival), lua.table_from(mia_)
    )


def test_una_mas_barata_va_por_delante():
    lua = runtime()
    assert _regla(lua, {"auctionID": 1, "buyout": 90}, {"auctionID": 5, "buyout": 100})


def test_al_mismo_precio_solo_adelanta_la_publicada_despues():
    lua = runtime()
    assert _regla(lua, {"auctionID": 6, "buyout": 100}, {"auctionID": 5, "buyout": 100})
    assert not _regla(lua, {"auctionID": 4, "buyout": 100}, {"auctionID": 5, "buyout": 100})


def test_una_mas_cara_no_adelanta():
    lua = runtime()
    assert not _regla(lua, {"auctionID": 9, "buyout": 101}, {"auctionID": 5, "buyout": 100})


def test_lo_tuyo_y_lo_de_tus_alts_no_cuenta_como_rival():
    lua = runtime()
    es_nuestro = lua.globals().WowAlertsReposteo.esNuestro

    def fila(**kw):
        return lua.table_from(en_venta(1, 100, **kw), recursive=True)

    assert es_nuestro(fila(propia=True))
    assert es_nuestro(fila(de_la_cuenta=True))
    assert es_nuestro(fila(dueno="Mbarval"))
    assert es_nuestro(fila(dueno="Mbarval-Sanguino"))
    assert not es_nuestro(fila(dueno="Extrano"))


def test_el_toc_carga_los_ficheros_en_orden():
    toc = (CARPETA / "WowAlertsExport.toc").read_text(encoding="utf-8")
    ficheros = [l.strip() for l in toc.splitlines() if l.strip() and not l.startswith("##")]
    assert ficheros == ["Vigilados.lua", "WowAlertsExport.lua", "Reposteo.lua"]


def test_el_exportador_sigue_funcionando_con_el_reposteo_cargado():
    lua = runtime(subastas=[mia(1, 100)])
    abrir_casa(lua)

    payload = json.loads(lua.globals().WowAlertsExportDB.payload)
    subastas = payload["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [1]
