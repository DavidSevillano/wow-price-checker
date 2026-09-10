"""El reposteo con una tecla, ejecutado fuera del juego.

Las APIs de WoW se sustituyen por dobles que apuntan cada llamada protegida
(cancelar, postear, confirmar, recoger correo). Lo que no se puede ver aqui --que
el juego acepte esas llamadas desde una tecla-- se comprueba a mano en la
Task 9 del plan.

Necesita `lupa`, que va en requirements-dev.txt. Sin el, los tests se saltan.

Corre sobre lupa.lua51, la misma version 5.1 que usa el juego.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.lua51")

CARPETA = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport"
GREBAS = 271440

DOBLES = r"""
-- Dobles de las APIs de WoW que usan el exportador y el reposteo.
local marcos = {}   -- frames creados, en orden de creacion, con sus eventos
mensajes = {}
LLAMADAS = {}    -- funciones protegidas, en el orden en que se llaman
BUSQUEDAS = {}   -- itemKeys pedidas a la casa y aun sin responder
BUSCADAS = 0     -- cuantas busquedas se han lanzado en total

-- Se guarda cuantos argumentos hubo (select("#", ...)) porque un nil en medio
-- no deja rastro en la tabla: sin "n" no habria forma de saber donde acababa
-- la llamada.
local function apuntar(...)
    LLAMADAS[#LLAMADAS + 1] = { n = select("#", ...), ... }
end

-- Cualquier metodo de interfaz que no importe devuelve un objeto que tampoco
-- hace nada, para poder encadenar llamadas (CreateFontString():SetText()...).
local NULO
NULO = setmetatable({}, { __index = function() return function() return NULO end end })

-- Cada frame se acuerda de que eventos ha registrado. Antes DISPARAR llamaba
-- a todos los manejadores para cualquier evento, y un RegisterEvent olvidado
-- en el addon de verdad nunca se habria notado aqui.
function CreateFrame(_, nombre)
    local registro = { eventos = {} }
    local frame = setmetatable({}, { __index = function() return function() return NULO end end })
    frame.RegisterEvent = function(self, evento) registro.eventos[evento] = true end
    frame.UnregisterEvent = function(self, evento) registro.eventos[evento] = nil end
    frame.SetScript = function(self, script, fn)
        if script == "OnEvent" then registro.onEvent = fn end
        rawset(self, "script_" .. script, fn)
    end
    registro.frame = frame
    marcos[#marcos + 1] = registro
    if nombre then _G[nombre] = frame end
    return frame
end

function DISPARAR(evento, ...)
    for _, registro in ipairs(marcos) do
        if registro.eventos[evento] and registro.onEvent then
            registro.onEvent(registro.frame, evento, ...)
        end
    end
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
TEMPORIZADORES = {}
C_Timer = {
    After = function(segundos, fn) TEMPORIZADORES[#TEMPORIZADORES + 1] = fn end,
    NewTicker = function() return { Cancel = function() end } end,
}
-- Vence todos los temporizadores pendientes, como si pasara el tiempo.
function VENCER_TEMPORIZADORES()
    local pendientes = TEMPORIZADORES
    TEMPORIZADORES = {}
    for _, fn in ipairs(pendientes) do fn() end
end

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
        apuntar("PostItem", loc.bagID, loc.slotIndex, duracion, cantidad, precio)
        -- Como el juego: el objeto queda bloqueado mientras se publica.
        local hueco = BOLSA[loc.bagID .. ":" .. loc.slotIndex]
        if hueco then hueco.isLocked = true end
        return NECESITA_CONFIRMAR
    end,
    ConfirmPostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("ConfirmPostItem", loc.bagID, loc.slotIndex, duracion, cantidad, precio)
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
function ItemLocation:CreateFromBagAndSlot(bolsa, hueco) return { bagID = bolsa, slotIndex = hueco } end
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


def abrir_casa(lua, esperar=True):
    """Abre la casa y, salvo que se pida lo contrario, deja pasar los segundos
    que hacen falta para fiarse de la lista de subastas propias."""
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    if esperar:
        lua.globals().RELOJ = lua.globals().RELOJ + 5


def pulsar(lua):
    return lua.globals().WowAlertsReposteo.Siguiente()


def responder_todo(lua):
    while lua.eval("#BUSQUEDAS") > 0:
        lua.globals().RESPONDER()


def cola(lua):
    return a_python(lua.eval('((WowAlertsExportDB.reposteo or {})["Sanguino-Pepe"]) or {}'))


def llamadas(lua):
    """Las llamadas protegidas registradas, leyendo cada una por su "n" para
    no perder los argumentos nil de en medio (p.ej. duracion o puja)."""
    tabla = lua.globals().LLAMADAS
    total = int(lua.eval("#LLAMADAS"))
    resultado = []
    for i in range(1, total + 1):
        llamada = tabla[i]
        n = int(llamada["n"])
        resultado.append(tuple(a_python(llamada[j]) for j in range(1, n + 1)))
    return resultado


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

    # Sin duenos y sin banderas de propiedad tampoco es nuestro: una fila asi
    # no puede colarse como "propia" por defecto.
    sin_duenos = lua.table_from(
        {
            "auctionID": 1,
            "buyoutAmount": 100,
            "owners": [],
            "containsOwnerItem": False,
            "containsAccountItem": False,
        },
        recursive=True,
    )
    assert not es_nuestro(sin_duenos)


# -- El arnes de eventos --------------------------------------------------------


def test_disparar_solo_entrega_a_quien_registro_el_evento():
    """Un RegisterEvent olvidado en el addon de verdad no debe pasar aqui
    desapercibido: DISPARAR solo tiene que llegar a quien se apunto."""
    lua = runtime()
    lua.execute(
        """
        VISTOS = {}
        local marco = CreateFrame("Frame")
        marco:RegisterEvent("EVENTO_APUNTADO")
        marco:SetScript("OnEvent", function(self, evento) VISTOS[#VISTOS + 1] = evento end)
        """
    )

    lua.globals().DISPARAR("EVENTO_NO_APUNTADO")
    assert a_python(lua.globals().VISTOS) == []

    lua.globals().DISPARAR("EVENTO_APUNTADO")
    assert a_python(lua.globals().VISTOS) == ["EVENTO_APUNTADO"]


# -- Llamadas protegidas --------------------------------------------------------


def test_llamadas_tolera_un_argumento_nulo_en_medio():
    lua = runtime()
    lua.execute('C_AuctionHouse.PostItem({bagID = 0, slotIndex = 3}, nil, 1, nil, 500)')
    assert llamadas(lua) == [("PostItem", 0, 3, None, 1, 500)]


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


# -- La busqueda -----------------------------------------------------------------


def detectar(lua):
    """Abre la casa, pulsa para buscar y deja que el servidor responda a todo."""
    abrir_casa(lua)
    pulsar(lua)
    responder_todo(lua)


def test_la_primera_pulsacion_busca_y_no_cancela_nada():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)

    assert pulsar(lua) == "buscar"
    assert lua.globals().BUSCADAS == 1
    assert llamadas(lua) == []


def test_sin_la_casa_abierta_no_busca():
    lua = runtime(subastas=[mia(10, 100_000)])
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 0


def test_si_te_adelantan_entra_en_la_cola_al_precio_del_rival():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000), en_venta(10, 100_000, dueno="Pepe", propia=True)])
    detectar(lua)

    [entrada] = cola(lua)
    assert entrada["auctionID"] == 10
    assert entrada["estado"] == "cancelar"
    assert entrada["precio"] == 90_000
    assert entrada["precioAnterior"] == 100_000
    assert (entrada["itemID"], entrada["ilvl"]) == (GREBAS, 311)


def test_al_mismo_precio_y_publicada_despues_tambien_te_adelanta():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 100_000)])
    detectar(lua)

    assert [e["precio"] for e in cola(lua)] == [100_000]


def test_si_vas_primero_no_entra_nada():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(9, 100_000), en_venta(12, 120_000)])
    detectar(lua)

    assert cola(lua) == []


def test_tus_alts_no_te_adelantan():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 50_000, dueno="Mbarval-Sanguino")])
    detectar(lua)

    assert cola(lua) == []


def test_solo_se_revisan_los_objetos_vigilados_y_activos():
    lua = runtime(subastas=[mia(10, 100_000, item_id=999), mia(11, 100_000, status=1)])
    detectar(lua)

    assert lua.globals().BUSCADAS == 0
    assert cola(lua) == []


def test_una_busqueda_por_objeto_e_ilvl_y_de_una_en_una():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1
    assert lua.eval("BUSQUEDAS[1].itemID") == GREBAS
    assert lua.eval("BUSQUEDAS[1].itemLevel") == 311

    lua.globals().RESPONDER()
    assert lua.globals().BUSCADAS == 2

    responder_todo(lua)
    # Las dos de ilvl 311 comparten busqueda.
    assert lua.globals().BUSCADAS == 2


def test_si_la_casa_no_admite_consultas_espera_a_que_avise():
    lua = runtime(subastas=[mia(10, 100_000)])
    lua.globals().SISTEMA_LISTO = False
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 0

    lua.globals().SISTEMA_LISTO = True
    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
    assert lua.globals().BUSCADAS == 1


def test_mientras_busca_otra_pulsacion_no_hace_nada():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)

    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 1


def test_la_cola_se_guarda_en_savedvariables_por_personaje():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)

    assert lua.eval('WowAlertsExportDB.reposteo["Sanguino-Pepe"][1].auctionID') == 10


def test_volver_a_buscar_actualiza_el_precio_sin_duplicar():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_casa(lua, [en_venta(11, 90_000), en_venta(13, 80_000)])
    detectar(lua)

    assert [e["precio"] for e in cola(lua)] == [80_000]


def test_si_ya_no_te_adelantan_sale_de_la_cola():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_no_busca_hasta_fiarse_de_la_lista_de_subastas():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    assert cola(lua) != []

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    buscadas_antes = lua.globals().BUSCADAS

    poner(lua, "SUBASTAS", [])
    abrir_casa(lua, esperar=False)
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == buscadas_antes
    assert cola(lua) != []

    poner(lua, "SUBASTAS", [mia(10, 100_000)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert pulsar(lua) == "buscar"


def test_si_la_respuesta_no_llega_se_salta_ese_objeto():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 2

    lua.globals().RESPONDER()
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 2


def test_una_respuesta_a_tiempo_no_la_salta_el_temporizador():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    abrir_casa(lua)
    pulsar(lua)
    lua.globals().RESPONDER()

    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 1
    assert [e["precio"] for e in cola(lua)] == [90_000]


def test_si_el_servidor_descarta_la_consulta_se_vuelve_a_pedir():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
    assert lua.globals().BUSCADAS == 2


def test_cerrar_la_casa_a_mitad_para_la_busqueda():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 1


def test_de_dos_subastas_solo_entra_la_que_va_por_detras():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)

    assert [e["auctionID"] for e in cola(lua)] == [10]


def test_no_busca_si_la_lista_de_subastas_no_ha_llegado_tras_abrir():
    """La espera de unos segundos no basta: tiene que haber llegado la lista."""
    lua = runtime(subastas=[mia(10, 100_000)])
    lua.execute("C_AuctionHouse.QueryOwnedAuctions = function() end")
    abrir_casa(lua)
    assert pulsar(lua) is None

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert pulsar(lua) == "buscar"


# -- Cancelar --------------------------------------------------------------------


def adelantadas(lua, *ids, precio=100_000, rival=90_000):
    """Tus subastas `ids`, todas adelantadas por un rival mas barato, ya buscadas."""
    poner(lua, "SUBASTAS", [mia(i, precio) for i in ids])
    en_la_casa(lua, [en_venta(999, rival)])
    detectar(lua)


def test_cada_pulsacion_cancela_una_sola():
    lua = runtime()
    adelantadas(lua, 10, 12, 14)

    for esperadas in (1, 2, 3):
        assert pulsar(lua) == "cancelar"
        assert len(llamadas(lua)) == esperadas

    assert llamadas(lua) == [("CancelAuction", 10), ("CancelAuction", 12), ("CancelAuction", 14)]


def test_cuando_el_juego_confirma_la_cancelacion_pasa_a_devuelta():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    assert cola(lua)[0]["estado"] == "cancelando"

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert cola(lua)[0]["estado"] == "devuelta"


def test_una_que_se_esta_cancelando_no_se_vuelve_a_cancelar():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)

    assert pulsar(lua) is None
    assert len(llamadas(lua)) == 1


def test_la_cancelacion_la_apunta_tambien_el_exportador():
    """Es lo que evita que el vigilante la cuente como venta."""
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)

    assert lua.eval('WowAlertsExportDB.canceladas["10"]') is not None


def test_si_el_juego_rechaza_la_cancelacion_vuelve_a_la_fila():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)  # sin AUCTION_CANCELED: el juego no la ha cancelado
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    detectar(lua)
    assert cola(lua)[0]["estado"] == "cancelar"


def test_si_desaparece_antes_de_cancelarla_sale_de_la_cola():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "SUBASTAS", [])  # se vendio mientras tanto
    detectar(lua)
    assert cola(lua) == []
