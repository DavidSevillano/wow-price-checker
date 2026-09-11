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
function CreateFrame(_, nombre, padre)
    local registro = { eventos = {} }
    local frame = setmetatable({}, { __index = function() return function() return NULO end end })
    frame.RegisterEvent = function(self, evento) registro.eventos[evento] = true end
    frame.UnregisterEvent = function(self, evento) registro.eventos[evento] = nil end
    frame.SetScript = function(self, script, fn)
        if script == "OnEvent" then registro.onEvent = fn end
        rawset(self, "script_" .. script, fn)
    end
    rawset(frame, "_texto", "")
    rawset(frame, "_habilitado", true)
    rawset(frame, "_padre", padre)
    rawset(frame, "_visible", true)
    frame.SetText = function(self, texto) rawset(self, "_texto", texto) end
    frame.GetText = function(self) return rawget(self, "_texto") end
    frame.Enable = function(self) rawset(self, "_habilitado", true) end
    frame.Disable = function(self) rawset(self, "_habilitado", false) end
    frame.IsEnabled = function(self) return rawget(self, "_habilitado") end
    frame.SetParent = function(self, p) rawset(self, "_padre", p) end
    frame.GetParent = function(self) return rawget(self, "_padre") end
    frame.Show = function(self) rawset(self, "_visible", true) end
    frame.Hide = function(self) rawset(self, "_visible", false) end
    frame.IsShown = function(self) return rawget(self, "_visible") end
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

AVISO_VISIBLE = nil
OCULTADOS = {}
function StaticPopup_Visible(nombre) return AVISO_VISIBLE == nombre end
function StaticPopup_Hide(nombre)
    OCULTADOS[#OCULTADOS + 1] = nombre
    if AVISO_VISIBLE == nombre then AVISO_VISIBLE = nil end
end

Enum = { AuctionHouseSortOrder = { Price = 0 } }

local function clave(k)
    return k.itemID .. ":" .. (k.itemLevel or 0) .. ":" .. (k.itemSuffix or 0)
end

SUBASTAS = {}
RESULTADOS = {}
SISTEMA_LISTO = true
NECESITA_CONFIRMAR = false
CREAR_SUBASTA = true

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
        if NECESITA_CONFIRMAR then
            -- El AuctionHouseFrame de Blizzard abre su aviso de precio al
            -- pedir confirmacion.
            AVISO_VISIBLE = "AUCTION_HOUSE_POST_WARNING"
        end
        if not NECESITA_CONFIRMAR and CREAR_SUBASTA then
            DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000 + #LLAMADAS)
        end
        return NECESITA_CONFIRMAR
    end,
    ConfirmPostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("ConfirmPostItem", loc.bagID, loc.slotIndex, duracion, cantidad, precio)
        if CREAR_SUBASTA then
            DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000 + #LLAMADAS)
        end
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

local function enHueco(loc) return BOLSA[loc.bagID .. ":" .. loc.slotIndex] end
C_Item = {
    DoesItemExist = function(loc) return enHueco(loc) ~= nil end,
    GetItemID = function(loc) local h = enHueco(loc); return h and h.itemID end,
    GetItemLink = function(loc) local h = enHueco(loc); return h and h.hyperlink end,
    IsBound = function(loc) local h = enHueco(loc); return h ~= nil and h.isBound == true end,
}
C_AuctionHouse.IsSellItemValid = function(loc)
    local h = enHueco(loc)
    return h ~= nil and h.isBound ~= true
end
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


def test_mientras_busca_no_cancela_lo_de_la_visita_anterior():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_si_la_busqueda_no_confirma_una_adelantada_no_se_cancela():
    """Cancelar cuesta el deposito: sin datos de esta visita, no se cancela."""
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    pulsar(lua)
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_cancelada_a_mano_pasa_a_devuelta():
    lua = runtime()
    adelantadas(lua, 10)

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert cola(lua)[0]["estado"] == "devuelta"


def test_no_cancela_lo_que_el_juego_no_deja_cancelar():
    lua = runtime()
    adelantadas(lua, 10, 12)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 12)]


def test_con_la_casa_saturada_de_consultas_no_cancela():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) is None
    assert llamadas(lua) == []
    assert cola(lua)[0]["estado"] == "cancelar"
    lua.globals().SISTEMA_LISTO = True
    assert pulsar(lua) == "cancelar"


# -- El correo -------------------------------------------------------------------


def devolver(lua, *ids, precio=100_000, rival=90_000):
    """Deja `ids` en la cola como devueltas: buscadas, canceladas y confirmadas."""
    adelantadas(lua, *ids, precio=precio, rival=rival)
    for i in ids:
        pulsar(lua)
        lua.globals().DISPARAR("AUCTION_CANCELED", i)
    poner(lua, "SUBASTAS", [])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "LLAMADAS", [])


def carta(item_id=GREBAS, ilvl=311, asunto="Auction cancelled: Greaves of the Noxious Depths"):
    return {"asunto": asunto, "nombre": "Greaves", "itemID": item_id, "enlace": f"[Grebas]ilvl{ilvl}"}


def abrir_buzon(lua):
    lua.globals().BUZON_ABIERTO = True
    lua.globals().DISPARAR("MAIL_SHOW")


def test_en_el_buzon_recoge_la_carta_de_lo_cancelado():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]


def test_no_recoge_cartas_que_no_son_de_la_cola():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(asunto="Hola"), carta(item_id=999), carta(ilvl=298)])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_no_recoge_si_el_objeto_ya_esta_en_la_bolsa():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) is None


def test_no_pide_dos_cartas_para_una_sola_devuelta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"
    assert pulsar(lua) is None
    assert len(llamadas(lua)) == 1


def test_con_dos_devueltas_recoge_dos_cartas_de_una_en_una():
    lua = runtime()
    devolver(lua, 10, 12)
    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)

    pulsar(lua)
    pulsar(lua)
    assert llamadas(lua) == [("TakeInboxItem", 1, 1), ("TakeInboxItem", 2, 1)]


def test_si_la_bolsa_estaba_llena_se_reintenta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    pulsar(lua)

    # La carta sigue ahi porque el objeto no cabia.
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert pulsar(lua) == "recoger"


def test_funciona_con_el_asunto_en_castellano():
    lua = runtime()
    lua.globals().AUCTION_REMOVED_MAIL_SUBJECT = "Subasta cancelada: %s"
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(asunto="Subasta cancelada: Grebas de las profundidades nocivas")])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


def test_una_carta_sin_datos_del_objeto_todavia_no_rompe_la_tecla():
    """El enlace de un adjunto puede no estar cargado aun."""
    lua = runtime()
    devolver(lua, 10)
    lua.execute(
        """
        local original = GetDetailedItemLevelInfo
        GetDetailedItemLevelInfo = function(enlace)
            assert(enlace ~= nil, "enlace nil")
            return original(enlace)
        end
        """
    )
    sin_enlace = carta()
    del sin_enlace["enlace"]
    poner(lua, "CORREO", [sin_enlace])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_copia_de_otro_ilvl_en_la_bolsa_no_frena_la_carta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl298", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


def test_cuenta_las_copias_de_todas_las_bolsas():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"4:16": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) is None


def test_no_recoge_para_una_que_aun_no_se_ha_cancelado():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_cerrar_y_abrir_el_buzon_permite_reintentar():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"


# -- Postear ---------------------------------------------------------------------


def en_la_bolsa(lua, *huecos, ilvl=311):
    poner(
        lua,
        "BOLSA",
        {
            f"0:{h}": {"itemID": GREBAS, "hyperlink": f"[Grebas]ilvl{ilvl}", "isLocked": False}
            for h in huecos
        },
    )


def volver_a_la_casa(lua, filas):
    """Con lo devuelto ya recogido, vuelves a la casa y pulsas para buscar."""
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    en_la_casa(lua, filas)
    detectar(lua)
    poner(lua, "LLAMADAS", [])


def test_postea_lo_devuelto_al_precio_del_rival():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua) == [("PostItem", 0, 3, 1, 1, 90_000)]
    assert cola(lua) == []


def test_si_el_rival_ha_bajado_se_iguala_su_precio_nuevo():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 85_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 85_000


def test_si_el_rival_ya_no_esta_se_repostea_al_precio_anterior():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 100_000


def test_un_rival_mas_caro_que_tu_precio_anterior_no_sube_el_precio():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 150_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 100_000


def test_sin_buscar_en_esta_visita_no_postea():
    """El precio de lo devuelto se recalcula en cada visita antes de postear."""
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)

    assert pulsar(lua) == "buscar"
    responder_todo(lua)
    assert pulsar(lua) == "postear"


def test_sin_el_objeto_en_la_bolsa_no_postea():
    lua = runtime()
    devolver(lua, 10)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_copia_bloqueada_no_se_usa():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    lua.execute('BOLSA["0:3"].isLocked = true')
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) is None


def test_con_dos_devueltas_postea_dos_con_dos_pulsaciones():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    pulsar(lua)
    pulsar(lua)
    assert [(c[0], c[2]) for c in llamadas(lua)] == [("PostItem", 3), ("PostItem", 4)]


def test_si_el_juego_pide_confirmacion_la_siguiente_pulsacion_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"
    assert len(cola(lua)) == 1

    assert pulsar(lua) == "confirmar"
    assert llamadas(lua)[-1] == ("ConfirmPostItem", 0, 3, 1, 1, 90_000)
    assert cola(lua) == []


def test_cancelar_va_antes_que_postear():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    poner(lua, "SUBASTAS", [mia(20, 100_000)])
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "cancelar"
    assert pulsar(lua) == "postear"


def test_con_la_casa_saturada_de_consultas_no_postea():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) is None
    assert llamadas(lua) == []
    lua.globals().SISTEMA_LISTO = True
    assert pulsar(lua) == "postear"


def test_cerrar_la_casa_olvida_la_confirmacion_pendiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    assert [c[0] for c in llamadas(lua)] == ["PostItem"]


def test_una_confirmacion_no_se_repite():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)
    assert pulsar(lua) == "confirmar"

    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("ConfirmPostItem") == 1


def test_si_la_busqueda_no_repasa_el_precio_no_se_postea():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_el_precio_repasado_no_vale_para_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # esta vez la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_postea_con_la_duracion_de_vigilados():
    lua = runtime()
    lua.execute("WowAlertsVigilados.duracion = 2")
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][3] == 2


def test_si_el_objeto_cambia_de_hueco_antes_de_confirmar_no_se_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda otra cosa y las grebas pasan al 4.
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    assert pulsar(lua) is None
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]
    # Se descarto la confirmacion, pero la entrada sigue "posteando": lo
    # decide la busqueda siguiente (I-2).
    assert [e["estado"] for e in cola(lua)] == ["posteando"]
    assert pulsar(lua) is None

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])  # SUBASTAS no tiene nada a ese precio
    assert [e["estado"] for e in cola(lua)] == ["devuelta"]

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_no_postea_una_copia_que_la_casa_no_acepta():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    lua.execute("C_AuctionHouse.IsSellItemValid = function(loc) return loc.slotIndex ~= 3 end")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_una_copia_ligada_no_se_postea_aunque_la_casa_la_acepte():
    lua = runtime()
    devolver(lua, 10)
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    lua.execute("C_AuctionHouse.IsSellItemValid = function() return true end")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_la_misma_pieza_de_otro_ilvl_en_el_hueco_no_se_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda la misma pieza pero de otro ilvl.
    poner(
        lua,
        "BOLSA",
        {"0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl298", "isLocked": False}},
    )
    assert pulsar(lua) is None
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]


def test_al_confirmar_se_cierra_el_aviso_de_precio_de_blizzard():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"
    assert lua.eval("AVISO_VISIBLE") == "AUCTION_HOUSE_POST_WARNING"

    assert pulsar(lua) == "confirmar"
    assert a_python(lua.globals().OCULTADOS) == ["AUCTION_HOUSE_POST_WARNING"]


def test_si_se_descarta_la_confirmacion_tambien_se_cierra_el_aviso():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda otra cosa y las grebas pasan al 4.
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == ["AUCTION_HOUSE_POST_WARNING"]
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]


def test_sin_confirmacion_no_se_toca_ningun_aviso():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert a_python(lua.globals().OCULTADOS) == []


def test_con_la_casa_saturada_la_confirmacion_espera():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == []
    assert lua.eval("AVISO_VISIBLE") == "AUCTION_HOUSE_POST_WARNING"
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]
    lua.globals().SISTEMA_LISTO = True
    assert pulsar(lua) == "confirmar"


def test_no_postea_una_copia_que_no_se_puede_vender():
    lua = runtime()
    devolver(lua, 10)
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_una_copia_ligada_en_la_bolsa_no_frena_la_carta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(
        lua,
        "BOLSA",
        {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True}},
    )
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


# -- Panel, tecla y garantias ----------------------------------------------------


def estado(lua):
    return lua.globals().WowAlertsReposteo.Estado()


def test_el_panel_dice_que_toca():
    lua = runtime()
    abrir_casa(lua, esperar=False)
    assert estado(lua) == "Leyendo tus subastas..."

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert estado(lua) == "Buscar undercuts"

    adelantadas(lua, 10, 12)
    assert estado(lua) == "Cancelar (2)"


def test_mientras_busca_el_panel_lo_dice():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)

    assert estado(lua) == "Buscando 1/2..."


def test_sin_nada_que_repostear_el_panel_lo_dice():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert estado(lua) == "Nada que repostear"


def test_con_una_confirmacion_pendiente_el_panel_la_pide():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)

    assert estado(lua) == "Confirmar posteo"


def test_en_el_buzon_el_panel_dice_si_hay_que_recoger():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert estado(lua) == "Recoger del buzon"

    poner(lua, "CORREO", [])
    assert estado(lua) == "Vuelve a la casa a postear"

    otro = runtime()
    abrir_buzon(otro)
    assert estado(otro) == "Nada que recoger"


def test_en_la_casa_el_panel_dice_si_postear_o_ir_al_buzon():
    lua = runtime()
    devolver(lua, 10)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert estado(lua) == "Recoge lo devuelto en el buzon"

    en_la_bolsa(lua, 3)
    assert estado(lua) == "Postear"


def test_si_no_se_pudo_repasar_el_precio_el_panel_lo_dice():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    pulsar(lua)
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_el_boton_dice_que_toca_y_se_desactiva_mientras_busca():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua, esperar=False)
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Leyendo tus subastas..."

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscar undercuts"
    assert lua.eval("WowAlertsReposteoBoton:IsEnabled()")

    pulsar(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscando 1/2..."
    assert not lua.eval("WowAlertsReposteoBoton:IsEnabled()")


def test_el_boton_se_muda_al_buzon():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    abrir_buzon(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == MailFrame")


def test_si_la_casa_aun_no_habia_cargado_el_boton_aparece_despues():
    lua = runtime(subastas=[mia(10, 100_000)])
    original = lua.globals().AuctionHouseFrame
    lua.globals().AuctionHouseFrame = None
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().AuctionHouseFrame = original

    assert lua.eval("WowAlertsReposteoBoton") is None

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert lua.eval("WowAlertsReposteoBoton") is not None
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")


def test_las_entradas_de_mas_de_48_horas_se_descartan():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 49 * 3600
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert cola(lua) == []
    assert pulsar(lua) is None


def test_el_boton_hace_lo_mismo_que_la_tecla():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)

    lua.eval("WowAlertsReposteoBoton.script_OnClick")()
    assert lua.globals().BUSCADAS == 1


def test_la_tecla_asignable_llama_a_siguiente():
    import xml.etree.ElementTree as ET

    arbol = ET.parse(CARPETA / "Bindings.xml")
    [binding] = arbol.getroot().findall("Binding")
    assert binding.get("name") == "WOWALERTS_SIGUIENTE"
    assert binding.text.strip() == "WowAlertsReposteo.Siguiente()"

    assert binding.get("header") == "WOWALERTS"

    lua = runtime()
    assert lua.globals().BINDING_NAME_WOWALERTS_SIGUIENTE
    assert lua.globals().BINDING_HEADER_WOWALERTS


def test_ninguna_pulsacion_llama_a_mas_de_una_funcion_protegida():
    """La regla que mantiene esto dentro de lo que el juego permite."""
    lua = runtime()

    def pulsar_contando(veces):
        for _ in range(veces):
            antes = len(llamadas(lua))
            pulsar(lua)
            assert len(llamadas(lua)) - antes <= 1

    adelantadas(lua, 10, 12)
    pulsar_contando(3)
    for i in (10, 12):
        lua.globals().DISPARAR("AUCTION_CANCELED", i)
    poner(lua, "SUBASTAS", [])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)
    pulsar_contando(3)

    lua.globals().BUZON_ABIERTO = False
    en_la_bolsa(lua, 3, 4)
    lua.globals().NECESITA_CONFIRMAR = True
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    pulsar_contando(1)
    responder_todo(lua)
    pulsar_contando(5)

    assert [c[0] for c in llamadas(lua)] == [
        "CancelAuction", "CancelAuction",
        "TakeInboxItem", "TakeInboxItem",
        "PostItem", "ConfirmPostItem", "PostItem", "ConfirmPostItem",
    ]


def test_si_el_aviso_ya_no_esta_abierto_no_se_intenta_cerrar():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # El jugador ha cerrado el aviso a mano.
    lua.globals().AVISO_VISIBLE = None
    # Se ordena la bolsa: en el hueco 3 queda otra cosa, y la confirmacion se
    # descarta.
    poner(
        lua,
        "BOLSA",
        {"0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False}},
    )
    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == []


def test_mientras_se_cancela_el_panel_lo_dice():
    lua = runtime()
    adelantadas(lua, 10)
    assert pulsar(lua) == "cancelar"
    assert estado(lua) == "Cancelando..."


def test_si_el_boton_estaba_en_el_buzon_y_la_casa_carga_tarde_se_muda():
    lua = runtime()
    abrir_buzon(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == MailFrame")

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")

    original = lua.globals().AuctionHouseFrame
    lua.globals().AuctionHouseFrame = None
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().AuctionHouseFrame = original

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")


def test_si_la_busqueda_no_confirmo_una_adelantada_el_panel_pide_repasar():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_el_recuento_de_cancelar_solo_cuenta_lo_que_se_puede_cancelar():
    lua = runtime()
    adelantadas(lua, 10, 12)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert estado(lua) == "Cancelar (1)"


def test_en_el_buzon_no_mira_la_bolsa_por_cartas_ajenas():
    lua = runtime()
    lua.execute(
        """
        MIRADAS = 0
        local original = C_Container.GetContainerItemInfo
        C_Container.GetContainerItemInfo = function(bolsa, hueco)
            MIRADAS = MIRADAS + 1
            return original(bolsa, hueco)
        end
        """
    )
    poner(lua, "CORREO", [carta(), carta(), carta()])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert lua.eval("MIRADAS") == 0


def test_la_version_del_toc_es_la_del_addon():
    """/wa dice la version del codigo; la lista de addons del juego, la del .toc."""
    import re

    toc = (CARPETA / "WowAlertsExport.toc").read_text(encoding="utf-8")
    lua = (CARPETA / "WowAlertsExport.lua").read_text(encoding="utf-8")

    en_toc = re.search(r"^## Version: (.+)$", toc, re.MULTILINE).group(1).strip()
    en_lua = re.search(r'^local ADDON_VERSION = "(.+)"$', lua, re.MULTILINE).group(1)
    assert en_toc == en_lua == "1.15"


# -- Lo que el juego confirma y lo que se repone por fuera --------------------


def test_postear_deja_la_entrada_hasta_que_el_juego_crea_la_subasta():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False

    assert pulsar(lua) == "postear"
    assert [e["estado"] for e in cola(lua)] == ["posteando"]
    assert estado(lua) == "Posteando..."

    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000)
    assert cola(lua) == []


def test_aceptar_en_el_aviso_de_blizzard_no_postea_otra_copia():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Aceptar en el aviso de Blizzard publica la copia del hueco 3.
    lua.execute('BOLSA["0:3"] = nil')
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000)

    assert cola(lua) == []
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)] == ["PostItem"]
    assert lua.globals().AVISO_VISIBLE is None


def test_un_posteo_sin_respuesta_vuelve_a_la_fila_en_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.execute('BOLSA["0:3"].isLocked = false')  # el posteo no llego a hacerse
    lua.globals().CREAR_SUBASTA = True
    detectar(lua)

    assert pulsar(lua) == "postear"
    assert cola(lua) == []


def test_si_la_repusiste_a_mano_se_olvida_al_abrir_el_buzon():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [mia(50, 90_000)])  # puesta a mano con Auctionator
    volver_a_la_casa(lua, [])
    assert len(cola(lua)) == 1  # en la casa no se sabe si es la misma copia

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert len(cola(lua)) == 1  # primera vez que falta: aun no se olvida

    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()
    assert cola(lua) == []


def test_otra_copia_puesta_antes_de_cancelar_no_cuenta_como_repuesta():
    lua = runtime()
    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    poner(lua, "SUBASTAS", [mia(12, 80_000)])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert [e["auctionID"] for e in cola(lua)] == [10]
    assert pulsar(lua) == "postear"


def test_lo_devuelto_que_ya_no_esta_ni_en_el_buzon_ni_en_la_bolsa_se_olvida():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert len(cola(lua)) == 1

    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()
    assert cola(lua) == []


def test_no_olvida_lo_devuelto_si_la_carta_puede_no_haber_llegado():
    lua = runtime()
    devolver(lua, 10)
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_no_olvida_lo_devuelto_con_el_buzon_a_medio_cargar():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    lua.execute("GetInboxNumItems = function() return 0, 3 end")
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_no_olvida_lo_devuelto_justo_despues_de_recogerlo():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    # La carta ya no esta y el objeto aun no ha llegado a la bolsa.
    poner(lua, "CORREO", [])
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_una_carta_pedida_hace_rato_se_puede_volver_a_pedir():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    # La bolsa estaba llena y el buzon no ha cambiado.
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert pulsar(lua) == "recoger"


def test_una_cancelacion_sin_respuesta_no_deja_el_panel_en_cancelando():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_un_posteo_sin_respuesta_no_deja_el_panel_en_posteando():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_la_cola_sobrevive_a_un_reload():
    lua = runtime()
    devolver(lua, 10)
    guardado = a_python(lua.globals().WowAlertsExportDB)

    otra = runtime()
    # WoW carga SavedVariables despues de ejecutar los ficheros del addon.
    poner(otra, "WowAlertsExportDB", guardado)
    en_la_bolsa(otra, 3)
    volver_a_la_casa(otra, [en_venta(999, 90_000)])

    assert pulsar(otra) == "postear"
    assert llamadas(otra)[-1][-1] == 90_000


def test_con_las_ventanas_cerradas_el_panel_no_recalcula():
    lua = runtime()
    devolver(lua, 10)
    abrir_buzon(lua)  # crea el boton
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.execute(
        """
        MIRADAS = 0
        local original = C_Container.GetContainerItemInfo
        C_Container.GetContainerItemInfo = function(...)
            MIRADAS = MIRADAS + 1
            return original(...)
        end
        """
    )
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")

    assert lua.globals().MIRADAS == 0


def test_la_segunda_copia_sigue_en_la_cola_tras_postear_la_primera():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # la que acaba de crear la tecla
    poner(lua, "BOLSA", {"0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    volver_a_la_casa(lua, [])

    assert [e["auctionID"] for e in cola(lua)] == [12]
    assert pulsar(lua) == "postear"


def test_poner_otra_copia_a_mano_no_saca_de_la_cola_lo_devuelto():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [mia(50, 70_000)])  # stock nuevo puesto a mano
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [])

    assert [e["auctionID"] for e in cola(lua)] == [10]
    assert pulsar(lua) == "postear"


def test_un_posteo_creado_sin_aviso_sale_en_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # si se creo, a ese precio
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_una_subasta_del_mismo_objeto_a_otro_precio_no_cierra_un_posteo():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 95_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert [(e["auctionID"], e["estado"]) for e in cola(lua)] == [(10, "devuelta")]


def test_no_olvida_lo_que_llega_a_la_bolsa_poco_despues():
    """Una carta recogida a mano o por otro addon tarda en llegar a la bolsa."""
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    en_la_bolsa(lua, 3)
    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()

    assert len(cola(lua)) == 1


def test_con_el_buzon_cerrado_no_olvida_nada():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().VENCER_TEMPORIZADORES()

    assert len(cola(lua)) == 1


def test_una_subasta_creada_mucho_despues_no_cierra_un_posteo_viejo():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().RELOJ = lua.globals().RELOJ + 60
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 7777)  # un posteo a mano de otra cosa

    assert len(cola(lua)) == 1


# -- Lo que no sobrevive a una visita, y lo que no se duplica -----------------


def test_una_marca_de_otra_visita_al_buzon_no_olvida_de_golpe():
    """La marca de que algo falta no se guarda: es de esta visita al buzon."""
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")  # marca que falta, en esta visita

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.globals().RELOJ = lua.globals().RELOJ + 3600
    lua.globals().AHORA = lua.globals().AHORA + 3600
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_aceptar_sin_aviso_de_creada_no_postea_otra_copia():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"

    # Se acepta desde el aviso de Blizzard, pero el aviso de creacion se pierde.
    lua.execute('BOLSA["0:3"] = nil')
    assert pulsar(lua) is None
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 1

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # la que se creo al aceptar
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []
    assert pulsar(lua) is None


def test_no_postea_otra_mientras_espera_a_que_se_cree_la_anterior():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False

    assert pulsar(lua) == "postear"
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 1

    lua.globals().RELOJ = lua.globals().RELOJ + 11
    assert pulsar(lua) == "postear"
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 2


def test_un_posteo_creado_sin_aviso_y_ya_vendido_tambien_sale():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000, status=1)])  # se creo y ya se vendio
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_el_buzon_programa_una_sola_revision():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    n = lua.eval("#TEMPORIZADORES")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    assert lua.eval("#TEMPORIZADORES") == n


def test_una_confirmacion_descartada_no_hace_olvidar_la_otra_copia():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: las grebas pasan a los huecos 5 y 6.
    en_la_bolsa(lua, 5, 6)
    assert pulsar(lua) is None  # se descarta la confirmacion
    lua.globals().NECESITA_CONFIRMAR = False
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    # No se sabe si la primera llego a crearse: la otra copia espera.
    assert pulsar(lua) is None
    assert estado(lua) == "Cierra y abre la casa para repasar precios"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert sorted(e["auctionID"] for e in cola(lua)) == [10, 12]
    assert pulsar(lua) == "postear"


def test_cerrar_la_casa_con_una_confirmacion_pendiente_deja_que_decida_la_busqueda():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    assert [e["estado"] for e in cola(lua)] == ["posteando"]

    lua.execute('BOLSA["0:3"].isLocked = false')  # no llego a crearse
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)
    assert [e["estado"] for e in cola(lua)] == ["devuelta"]


def test_mientras_espera_a_que_se_cree_un_posteo_el_panel_no_dice_postear():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    assert estado(lua) == "Posteando..."
