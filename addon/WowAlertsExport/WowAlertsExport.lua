-- Exporta tus subastas activas a SavedVariables como una cadena JSON.
--
-- El lado Python solo tiene que extraer esa cadena y hacer json.loads, en vez
-- de interpretar tablas de Lua. WoW unicamente escribe SavedVariables a disco
-- al salir del juego, al hacer logout o con /reload, asi que el addon avisa en
-- pantalla cuando hay subastas recogidas que todavia no se han volcado.

local FORMAT_VERSION = 1

WowAlertsExportDB = WowAlertsExportDB or {}

-- Lo que habia en disco al arrancar. Comparar contra esto es lo que permite
-- saber si queda algo sin volcar.
local volcadoEnDisco = nil

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
    datos[clave] = {
        character = nombre,
        realm = reino,
        exportedAt = time(),
        auctions = recogerSubastas(),
    }

    WowAlertsExportDB.personajes = datos
    WowAlertsExportDB.version = FORMAT_VERSION
    WowAlertsExportDB.payload = encode({
        version = FORMAT_VERSION,
        personajes = datos,
    })

    return #datos[clave].auctions
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

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("OWNED_AUCTIONS_UPDATED")
frame:RegisterEvent("PLAYER_LOGOUT")

frame:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 == "WowAlertsExport" then
            volcadoEnDisco = WowAlertsExportDB.payload
        end
    elseif event == "AUCTION_HOUSE_SHOW" then
        C_AuctionHouse.QueryOwnedAuctions({})
    elseif event == "OWNED_AUCTIONS_UPDATED" then
        local cuantas = guardar()
        print(("|cffffd200WoW Alerts:|r %d subasta(s) tuyas registradas."):format(cuantas))
        avisarSiFaltaVolcar()
    elseif event == "PLAYER_LOGOUT" then
        guardar()
    end
end)

SLASH_WOWALERTS1 = "/wowalerts"
SlashCmdList["WOWALERTS"] = function()
    local cuantas = guardar()
    print(("|cffffd200WoW Alerts:|r %d subasta(s) registradas de este personaje."):format(cuantas))
    avisarSiFaltaVolcar()
end
