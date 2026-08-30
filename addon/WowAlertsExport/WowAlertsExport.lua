-- Exporta tus subastas activas a SavedVariables como una cadena JSON.
--
-- El lado Python solo tiene que extraer esa cadena y hacer json.loads, en vez
-- de interpretar tablas de Lua. WoW unicamente escribe SavedVariables a disco
-- al salir del juego, al hacer logout o con /reload, asi que el addon avisa en
-- pantalla cuando hay subastas recogidas que todavia no se han volcado.

local FORMAT_VERSION = 1
-- Version del addon, para saber que codigo se esta ejecutando de verdad.
local ADDON_VERSION = "1.2"

WowAlertsExportDB = WowAlertsExportDB or {}

-- Lo que habia en disco al arrancar. Comparar contra esto es lo que permite
-- saber si queda algo sin volcar.
local volcadoEnDisco = nil

-- El juego solo conoce tus subastas mientras la Casa de Subastas esta abierta:
-- con ella cerrada, GetNumOwnedAuctions() devuelve 0. La regla para no perder
-- datos por eso esta en guardar(), y no depende de ningun evento: una bandera
-- levantada al abrir la casa se pierde con cualquier /reload, y entonces el
-- addon se queda creyendo que esta cerrada para siempre.

-- ---------------------------------------------------------------------------
--  Codificacion JSON minima (solo los tipos que usamos)
-- ---------------------------------------------------------------------------

local function escapeString(s)
    s = tostring(s)
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    return '"' .. s .. '"'
end

local encode

local function encodeArray(t)
    local parts = {}
    for i = 1, #t do
        parts[#parts + 1] = encode(t[i])
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

local function encodeObject(t)
    -- Claves ordenadas: asi dos volcados con los mismos datos producen la misma
    -- cadena y el sincronizador puede saltarse el commit.
    local keys = {}
    for key in pairs(t) do
        keys[#keys + 1] = key
    end
    table.sort(keys)

    local parts = {}
    for _, key in ipairs(keys) do
        parts[#parts + 1] = escapeString(key) .. ":" .. encode(t[key])
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

encode = function(value)
    local kind = type(value)
    if kind == "number" then
        return string.format("%d", value)
    elseif kind == "string" then
        return escapeString(value)
    elseif kind == "boolean" then
        return value and "true" or "false"
    elseif kind == "table" then
        if #value > 0 or next(value) == nil then
            return encodeArray(value)
        end
        return encodeObject(value)
    end
    return "null"
end

-- ---------------------------------------------------------------------------
--  Lectura de tus subastas
-- ---------------------------------------------------------------------------

-- Los bonus ids viven dentro del enlace del objeto. No los usa la deteccion,
-- pero se exportan para poder ampliar el mapa de ilvl del config mas adelante.
local function bonusIDsFromLink(link)
    local ids = {}
    if not link then
        return ids
    end
    local payload = link:match("|Hitem:([%-%d:]*)")
    if not payload then
        return ids
    end

    local parts = {}
    for value in (payload .. ":"):gmatch("([^:]*):") do
        parts[#parts + 1] = value
    end

    -- Posicion 13 del enlace: cuantos bonus ids vienen detras.
    local count = tonumber(parts[13]) or 0
    for i = 1, count do
        local id = tonumber(parts[13 + i])
        if id then
            ids[#ids + 1] = id
        end
    end
    return ids
end

local function recogerSubastas()
    local subastas = {}
    local total = C_AuctionHouse.GetNumOwnedAuctions()

    for index = 1, total do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(index)
        -- Sin compra directa no hay nada que comparar: una subasta que solo
        -- admite pujas no compite en precio con las demas.
        if info and info.buyoutAmount and info.buyoutAmount > 0 then
            local itemKey = info.itemKey or {}
            local link = info.itemLink
            local ilvl = nil
            if link then
                ilvl = GetDetailedItemLevelInfo(link)
            end
            ilvl = ilvl or itemKey.itemLevel

            local nombre = nil
            if link then
                nombre = link:match("%[(.-)%]")
            end

            if itemKey.itemID and ilvl then
                subastas[#subastas + 1] = {
                    auctionID = info.auctionID,
                    itemID = itemKey.itemID,
                    itemName = nombre or ("Objeto " .. itemKey.itemID),
                    ilvl = ilvl,
                    bonusIDs = bonusIDsFromLink(link),
                    buyout = info.buyoutAmount,
                    quantity = info.quantity or 1,
                }
            end
        end
    end

    return subastas
end

-- ---------------------------------------------------------------------------
--  Volcado
-- ---------------------------------------------------------------------------

-- Pedirle al servidor tus subastas. Con la casa de subastas cerrada esto no
-- vale para nada y puede protestar, asi que se envuelve en pcall.
local function pedirSubastas()
    pcall(C_AuctionHouse.QueryOwnedAuctions, {})
end

-- Igual, pero agrupando las peticiones seguidas en una sola. Al postear una
-- tanda de veinte objetos llegan veinte eventos, y la casa de subastas limita
-- cuantas consultas admite seguidas.
local refrescoPendiente = false

local function pedirSubastasPronto()
    if refrescoPendiente then
        return
    end
    refrescoPendiente = true
    C_Timer.After(2, function()
        refrescoPendiente = false
        pedirSubastas()
    end)
end


local function claveDePersonaje()
    local nombre = UnitName("player")
    local reino = GetRealmName()
    return reino .. "-" .. nombre, nombre, reino
end

local function guardar()
    -- Se parte de lo ya guardado para no borrar las subastas de los demas
    -- personajes: cada uno actualiza solo su propia entrada.
    local datos = WowAlertsExportDB.personajes or {}

    local clave, nombre, reino = claveDePersonaje()
    local recogidas = recogerSubastas()
    local previo = datos[clave]

    -- Leer cero subastas teniendo ya algo guardado no significa que las hayas
    -- cancelado: significa que ahora mismo no se pueden leer, casi siempre
    -- porque la casa de subastas esta cerrada. Conservar lo anterior es la
    -- opcion segura, porque el vigilante descarta solo las que ya no existen.
    if #recogidas == 0 and previo and #(previo.auctions or {}) > 0 then
        return nil
    end

    datos[clave] = {
        character = nombre,
        realm = reino,
        exportedAt = time(),
        auctions = recogidas,
    }

    WowAlertsExportDB.personajes = datos
    WowAlertsExportDB.version = FORMAT_VERSION
    WowAlertsExportDB.payload = encode({
        version = FORMAT_VERSION,
        personajes = datos,
    })

    return #recogidas
end

local function avisarSiFaltaVolcar()
    if WowAlertsExportDB.payload == volcadoEnDisco then
        return
    end
    print(
        "|cffffd200WoW Alerts:|r subastas actualizadas pero |cffff7f7fsin guardar"
            .. " a disco|r. Haz |cff00ff00/reload|r (o sal del juego) para que el"
            .. " vigilante de undercuts se entere."
    )
end

-- ---------------------------------------------------------------------------
--  Eventos
-- ---------------------------------------------------------------------------

-- No hace falta engancharse a PLAYER_LOGOUT: lo recogido ya vive en
-- WowAlertsExportDB, y WoW escribe esa tabla a disco al salir por su cuenta.
local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("OWNED_AUCTIONS_UPDATED")
-- Postear o cancelar cambia tus subastas sin cerrar la casa. Sin estos dos, el
-- addon se quedaba con la foto de cuando la abriste.
frame:RegisterEvent("AUCTION_HOUSE_AUCTION_CREATED")
frame:RegisterEvent("AUCTION_CANCELED")

frame:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 == "WowAlertsExport" then
            volcadoEnDisco = WowAlertsExportDB.payload
        end
    elseif event == "AUCTION_HOUSE_SHOW" then
        pedirSubastas()
    elseif event == "AUCTION_HOUSE_AUCTION_CREATED" or event == "AUCTION_CANCELED" then
        pedirSubastasPronto()
    elseif event == "OWNED_AUCTIONS_UPDATED" then
        local cuantas = guardar()
        if cuantas then
            print(("|cffffd200WoW Alerts:|r %d subasta(s) tuyas registradas."):format(cuantas))
            avisarSiFaltaVolcar()
        end
    end
end)

SLASH_WOWALERTS1 = "/wowalerts"
SLASH_WOWALERTS2 = "/wa"
SlashCmdList["WOWALERTS"] = function()
    local clave, nombre, reino = claveDePersonaje()
    print(("|cffffd200WoW Alerts v%s|r · %s de %s"):format(ADDON_VERSION, nombre, reino))
    print(("  la casa de subastas dice que tienes %d subasta(s) ahora mismo."):format(
        C_AuctionHouse.GetNumOwnedAuctions()
    ))

    -- Se vuelve a pedir por si la casa de subastas ya estaba abierta cuando el
    -- addon se cargo, que es justo lo que pasa despues de un /reload: el evento
    -- de apertura no llega a dispararse.
    pedirSubastas()

    local cuantas = guardar()
    if not cuantas then
        local previo = (WowAlertsExportDB.personajes or {})[claveDePersonaje()]
        print(
            ("|cffffd200WoW Alerts:|r no puedo leer nada ahora mismo; conservo "
                .. "las %d que tenia. Abre la Casa de Subastas y vuelve a "
                .. "probar."):format(#((previo or {}).auctions or {}))
        )
        return
    end
    print(("|cffffd200WoW Alerts:|r %d subasta(s) registradas de este personaje."):format(cuantas))
    avisarSiFaltaVolcar()
end
