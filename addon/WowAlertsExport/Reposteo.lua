-- Reposteo con una tecla.
--
-- Cancelar lo adelantado, recoger el correo y volver a postear, pulsando una
-- sola tecla. Cada pulsacion hace UNA accion y nunca mas: cancelar, postear,
-- confirmar y recoger correo solo funcionan en respuesta directa a una tecla o
-- un clic, y encadenarlas es justo lo que el juego bloquea. Es lo mismo que
-- hace la tecla de "Cancel Undercut" de Auctionator.
--
-- Que objetos se repostean y que personajes son tuyos lo dice Vigilados.lua,
-- que genera generar_vigilados.py desde config.yaml.

local R = {}
WowAlertsReposteo = R

local function vigilados()
    return WowAlertsVigilados or { objetos = {}, personajes = {}, duracion = 1 }
end

-- ---------------------------------------------------------------------------
--  Quien te adelanta
-- ---------------------------------------------------------------------------

-- La misma regla que wowalerts/undercut.py: mas barata adelanta siempre; al
-- mismo precio, solo la publicada despues, y el id de subasta crece con el
-- tiempo.
function R.vaPorDelante(rival, mia)
    if rival.buyout < mia.buyout then
        return true
    end
    return rival.buyout == mia.buyout and rival.auctionID > mia.auctionID
end

local function sinReino(nombre)
    return (tostring(nombre):match("^([^%-]+)"))
end

-- Lo tuyo no compite contigo. El juego marca lo de este personaje y lo de su
-- cuenta de juego, pero no lo de tus otras cuentas (WoW 2 y WoW 3): esos se
-- reconocen por el nombre.
function R.esNuestro(resultado)
    if resultado.containsOwnerItem or resultado.containsAccountItem then
        return true
    end
    local mios = {}
    for _, nombre in ipairs(vigilados().personajes) do
        mios[nombre] = true
    end
    for _, dueno in ipairs(resultado.owners or {}) do
        if mios[sinReino(dueno)] then
            return true
        end
    end
    return false
end

-- ---------------------------------------------------------------------------
--  La cola
-- ---------------------------------------------------------------------------
--  Una lista por personaje en WowAlertsExportDB.reposteo, para que sobreviva a
--  la ida al buzon, a un /reload y a cerrar el juego. Cada entrada pasa por
--  tres estados: "cancelar", "cancelando" (esperando AUCTION_CANCELED) y
--  "devuelta", y sale de la cola al postearse.

-- Horas que vive una entrada. Con listados de 12 h, algo que lleva dos dias en
-- la cola ya no describe nada que haya que repostear.
local HORAS_DE_VIDA = 48

local function clavePersonaje()
    return GetRealmName() .. "-" .. UnitName("player")
end

-- Se lee WowAlertsExportDB cada vez y no se guarda en una local: WoW reemplaza
-- esa tabla por la de disco despues de cargar este fichero.
local function cola()
    WowAlertsExportDB = WowAlertsExportDB or {}
    WowAlertsExportDB.reposteo = WowAlertsExportDB.reposteo or {}
    local clave = clavePersonaje()
    WowAlertsExportDB.reposteo[clave] = WowAlertsExportDB.reposteo[clave] or {}
    return WowAlertsExportDB.reposteo[clave]
end

local function buscarEntrada(auctionID)
    for i, entrada in ipairs(cola()) do
        if entrada.auctionID == auctionID then
            return entrada, i
        end
    end
    return nil, nil
end

local function quitarEntrada(auctionID)
    local _, i = buscarEntrada(auctionID)
    if i then
        table.remove(cola(), i)
    end
end

-- El panel se dibuja en la Task 7; hasta entonces no hay nada que refrescar.
function R.refrescarPanel() end

-- ---------------------------------------------------------------------------
--  La busqueda
-- ---------------------------------------------------------------------------

local function casaAbierta()
    return AuctionHouseFrame ~= nil and AuctionHouseFrame:IsShown()
end

local function claveDe(itemKey)
    return itemKey.itemID .. ":" .. (itemKey.itemLevel or 0) .. ":" .. (itemKey.itemSuffix or 0)
end

-- Todo esto vive en locales a proposito: cerrar la casa o hacer /reload obliga
-- a buscar otra vez, que es lo correcto, porque los precios han podido moverse.
local buscadoEnEstaVisita = false
local grupos = {}        -- clave -> { itemKey, mias = {...}, devueltas = {...} }
local ordenGrupos = {}
local siguienteGrupo = 1
local esperando = nil    -- clave del grupo cuya respuesta se espera
local repasadas = {}     -- auctionID -> true: devueltas con el precio al dia

local function reiniciarBusqueda()
    grupos, ordenGrupos, siguienteGrupo, esperando = {}, {}, 1, nil
end

local function buscando()
    return buscadoEnEstaVisita and siguienteGrupo <= #ordenGrupos
end

local function anadirAGrupo(itemKey)
    local clave = claveDe(itemKey)
    if not grupos[clave] then
        grupos[clave] = {
            itemKey = {
                itemID = itemKey.itemID,
                itemLevel = itemKey.itemLevel,
                itemSuffix = itemKey.itemSuffix,
            },
            mias = {},
            devueltas = {},
        }
        ordenGrupos[#ordenGrupos + 1] = clave
    end
    return grupos[clave]
end

-- Agrupa por objeto e ilvl lo que hay que mirar, y de paso limpia la cola.
local function prepararBusqueda()
    reiniciarBusqueda()
    local objetos = vigilados().objetos
    local activas = {}

    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        local itemKey = info and info.itemKey
        -- status 0 es activa. 1 es vendida y pendiente de cobro: no se toca.
        if info and info.status == 0 and (info.buyoutAmount or 0) > 0
            and itemKey and objetos[itemKey.itemID] then
            activas[info.auctionID] = true
            local grupo = anadirAGrupo(itemKey)
            grupo.mias[#grupo.mias + 1] = {
                auctionID = info.auctionID,
                buyout = info.buyoutAmount,
                itemID = itemKey.itemID,
                ilvl = GetDetailedItemLevelInfo(info.itemLink) or itemKey.itemLevel,
            }
        end
    end

    local ahora = time()
    local entradas = cola()
    for i = #entradas, 1, -1 do
        local e = entradas[i]
        if ahora - (e.desde or 0) > HORAS_DE_VIDA * 3600 then
            table.remove(entradas, i)
        elseif e.estado == "cancelar" or e.estado == "cancelando" then
            if activas[e.auctionID] then
                -- Sigue activa: si estaba "cancelando", el juego rechazo la
                -- cancelacion, y vuelve a la fila.
                e.estado = "cancelar"
            else
                -- Ya no esta: vendida o caducada antes de poder cancelarla.
                table.remove(entradas, i)
            end
        elseif e.estado == "devuelta" then
            local grupo = anadirAGrupo(e.itemKey)
            grupo.devueltas[#grupo.devueltas + 1] = e
        end
    end
end

local function lanzarSiguiente()
    if esperando or not buscando() then
        return
    end
    if not C_AuctionHouse.IsThrottledMessageSystemReady() then
        -- La casa limita las consultas seguidas. Se reintenta con
        -- AUCTION_HOUSE_THROTTLED_SYSTEM_READY.
        return
    end
    esperando = ordenGrupos[siguienteGrupo]
    C_AuctionHouse.SendSearchQuery(
        grupos[esperando].itemKey,
        { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } },
        true
    )
end

-- El precio del rival mas barato que va por delante de `mia`, o nil.
local function mejorRival(itemKey, mia)
    local mejor = nil
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local fila = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if fila and (fila.buyoutAmount or 0) > 0 and not R.esNuestro(fila) then
            local rival = { auctionID = fila.auctionID, buyout = fila.buyoutAmount }
            if R.vaPorDelante(rival, mia) and (not mejor or rival.buyout < mejor) then
                mejor = rival.buyout
            end
        end
    end
    return mejor
end

local function procesarGrupo(grupo)
    for _, m in ipairs(grupo.mias) do
        local precio = mejorRival(grupo.itemKey, m)
        local entrada = buscarEntrada(m.auctionID)
        if precio then
            if not entrada then
                entrada = {
                    auctionID = m.auctionID,
                    itemKey = grupo.itemKey,
                    itemID = m.itemID,
                    ilvl = m.ilvl,
                    precioAnterior = m.buyout,
                    estado = "cancelar",
                    desde = time(),
                }
                local entradas = cola()
                entradas[#entradas + 1] = entrada
            end
            if entrada.estado == "cancelar" then
                entrada.precio = precio
            end
        elseif entrada and entrada.estado == "cancelar" then
            quitarEntrada(m.auctionID)
        end
    end

    -- Repaso de lo devuelto: tu subasta nueva sera la mas reciente, asi que
    -- solo te adelanta lo que este por debajo de tu precio anterior. Si ya no
    -- queda nadie ahi, se repostea a ese precio: igualar, nunca subir.
    for _, e in ipairs(grupo.devueltas) do
        local rival = mejorRival(grupo.itemKey, { auctionID = math.huge, buyout = e.precioAnterior })
        e.precio = rival or e.precioAnterior
        repasadas[e.auctionID] = true
    end
end

local function alResponder(itemKey)
    if not esperando or not itemKey or claveDe(itemKey) ~= esperando then
        return
    end
    procesarGrupo(grupos[esperando])
    esperando = nil
    siguienteGrupo = siguienteGrupo + 1
    lanzarSiguiente()
end

local function empezarBusqueda()
    buscadoEnEstaVisita = true
    prepararBusqueda()
    lanzarSiguiente()
end

-- ---------------------------------------------------------------------------
--  La tecla
-- ---------------------------------------------------------------------------

-- Hace UNA accion y devuelve cual ("buscar"), o nil si no habia nada que hacer.
function R.Siguiente()
    local hecho = nil
    if casaAbierta() and not buscadoEnEstaVisita then
        empezarBusqueda()
        hecho = "buscar"
    end
    R.refrescarPanel()
    return hecho
end

-- ---------------------------------------------------------------------------
--  Eventos
-- ---------------------------------------------------------------------------

local frame = CreateFrame("Frame")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("ITEM_SEARCH_RESULTS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")

frame:SetScript("OnEvent", function(_, evento, arg1)
    if evento == "AUCTION_HOUSE_SHOW" then
        buscadoEnEstaVisita = false
        repasadas = {}
        reiniciarBusqueda()
    elseif evento == "AUCTION_HOUSE_CLOSED" then
        esperando = nil
    elseif evento == "ITEM_SEARCH_RESULTS_UPDATED" then
        alResponder(arg1)
    elseif evento == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
        lanzarSiguiente()
    end
    R.refrescarPanel()
end)
