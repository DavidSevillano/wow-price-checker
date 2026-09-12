-- La ventana "Tus subastas": que tienes puesto y que te han adelantado.
--
-- Solo dibuja. Quien clasifica es WowAlertsReposteo.Subastas(), y quien manda
-- redibujar es R.refrescarPanel().

local V = {}
WowAlertsVentana = V

local ANCHO = 330
local ALTO_FILA = 34
local ALTO_MAXIMO = 560

local COLORES = {
    adelantada = { 1, 0.29, 0.24, "ADELANTADAS" },
    primera = { 0.25, 0.85, 0.29, "VAS PRIMERO" },
    sinmirar = { 0.56, 0.53, 0.48, "SIN MIRAR TODAVIA" },
    novigilada = { 0.56, 0.53, 0.48, "NO VIGILADAS" },
}
local ORDEN = { "adelantada", "primera", "sinmirar", "novigilada" }

local marco, contenido, filas, cabecera
local ocultaAdrede = false

local function oro(cobre)
    return tostring(math.floor((cobre or 0) / 10000)) .. " o"
end

local function crearMarco()
    marco = CreateFrame("Frame", "WowAlertsVentana", UIParent, "BasicFrameTemplateWithInset")
    marco:SetSize(ANCHO, 200)
    marco:SetFrameStrata("HIGH")
    marco:SetMovable(true)
    marco:EnableMouse(true)
    marco:RegisterForDrag("LeftButton")
    marco:SetScript("OnDragStart", marco.StartMoving)
    marco:SetScript("OnDragStop", marco.StopMovingOrSizing)
    marco:SetScript("OnHide", function()
        -- Si la cierras tu, no vuelve hasta la proxima vez que abras la casa.
        if AuctionHouseFrame and AuctionHouseFrame:IsShown() then
            ocultaAdrede = true
        end
    end)

    -- No se toca marco.TitleText: segun el cliente, la plantilla lo trae
    -- directo o metido dentro de un TitleContainer, y no siempre existe de
    -- la misma forma. Se pone un titulo propio anclado a TitleBg, que es
    -- estable en BasicFrameTemplateWithInset desde hace mucho.
    marco.titulo = marco:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    marco.titulo:SetPoint("TOP", marco.TitleBg, "TOP", 0, -3)
    marco.titulo:SetText("Tus subastas")

    cabecera = marco:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cabecera:SetPoint("TOPLEFT", marco, "TOPLEFT", 14, -30)

    local scroll = CreateFrame("ScrollFrame", nil, marco, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", marco, "TOPLEFT", 10, -48)
    scroll:SetPoint("BOTTOMRIGHT", marco, "BOTTOMRIGHT", -30, 10)
    contenido = CreateFrame("Frame", nil, scroll)
    contenido:SetSize(ANCHO - 46, 10)
    scroll:SetScrollChild(contenido)

    filas = {}
end

-- Una fila reutilizable: icono, nombre, detalle e ilvl.
local function fila(indice)
    if filas[indice] then
        return filas[indice]
    end
    local f = CreateFrame("Frame", nil, contenido)
    f:SetSize(ANCHO - 50, ALTO_FILA)
    f.icono = f:CreateTexture(nil, "ARTWORK")
    f.icono:SetSize(26, 26)
    f.icono:SetPoint("LEFT", f, "LEFT", 0, 0)
    f.nombre = f:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    f.nombre:SetPoint("TOPLEFT", f.icono, "TOPRIGHT", 6, 0)
    f.nombre:SetWidth(ANCHO - 130)
    f.nombre:SetJustifyH("LEFT")
    f.nombre:SetWordWrap(false)
    f.detalle = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    f.detalle:SetPoint("TOPLEFT", f.nombre, "BOTTOMLEFT", 0, -2)
    f.ilvl = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    f.ilvl:SetPoint("RIGHT", f, "RIGHT", 0, 0)
    filas[indice] = f
    return f
end

-- Un titulo de grupo, con el mismo hueco que una fila pero mas bajo.
local function titulo(indice, texto, r, g, b)
    local f = fila(indice)
    f.icono:Hide()
    f.nombre:SetText(texto)
    f.nombre:SetTextColor(r, g, b)
    f.detalle:SetText("")
    f.ilvl:SetText("")
    f:Show()
    return f
end

-- Los nombres nuevos de estas dos viven en C_Item; se deja el viejo de
-- recambio por si el cliente aun no los tiene.
local datosDelObjeto = (C_Item and C_Item.GetItemInfo) or GetItemInfo
local colorDeCalidad = (C_Item and C_Item.GetItemQualityColor) or GetItemQualityColor

local function pintarFila(indice, datos)
    local f = fila(indice)
    local nombre, _, calidad, _, _, _, _, _, _, icono = datosDelObjeto(datos.enlace or "")
    f.icono:SetTexture(icono or "Interface\\Icons\\INV_Misc_QuestionMark")
    f.icono:Show()
    local r, g, b = colorDeCalidad(calidad or 1)
    f.nombre:SetText(nombre or (datos.enlace or "Cargando..."))
    f.nombre:SetTextColor(r, g, b)
    if datos.grupo == "adelantada" then
        if datos.igualada then
            f.detalle:SetText(("%s  |cffff4a3d> te igualan|r"):format(oro(datos.precio)))
        else
            f.detalle:SetText(("%s  |cffff4a3d> rival %s|r"):format(
                oro(datos.precio), oro(datos.precioRival)))
        end
    else
        f.detalle:SetText(oro(datos.precio))
    end
    -- Las recetas y lo que no escala salen con ilvl 1: no se muestra.
    f.ilvl:SetText((datos.ilvl and datos.ilvl > 1) and tostring(datos.ilvl) or "")
    f:Show()
end

function V.Refrescar()
    if not AuctionHouseFrame or not AuctionHouseFrame:IsShown() then
        if marco then
            marco:Hide()
        end
        return
    end
    if ocultaAdrede then
        return
    end
    -- Si alguien desactiva Reposteo.lua, esto no debe reventar: no hay datos
    -- que pintar, asi que no se hace nada.
    if not WowAlertsReposteo or not WowAlertsReposteo.Subastas then
        return
    end
    if not marco then
        crearMarco()
    end

    local porGrupo = {}
    local total, adelantadas = 0, 0
    for _, datos in ipairs(WowAlertsReposteo.Subastas()) do
        porGrupo[datos.grupo] = porGrupo[datos.grupo] or {}
        table.insert(porGrupo[datos.grupo], datos)
        total = total + 1
        if datos.grupo == "adelantada" then
            adelantadas = adelantadas + 1
        end
    end

    cabecera:SetText(("%s puestas  -  |cffff4a3d%s adelantadas|r"):format(total, adelantadas))

    local indice, alto = 0, 0
    for _, grupo in ipairs(ORDEN) do
        local lista = porGrupo[grupo]
        if lista then
            local color = COLORES[grupo]
            indice = indice + 1
            local t = titulo(indice, color[4], color[1], color[2], color[3])
            t:ClearAllPoints()
            t:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
            alto = alto + 18
            for _, datos in ipairs(lista) do
                indice = indice + 1
                pintarFila(indice, datos)
                local f = filas[indice]
                f:ClearAllPoints()
                f:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
                alto = alto + ALTO_FILA
            end
        end
    end
    for sobra = indice + 1, #filas do
        filas[sobra]:Hide()
    end

    contenido:SetHeight(math.max(alto, 10))
    marco:SetHeight(math.min(alto + 70, ALTO_MAXIMO))
    marco:ClearAllPoints()
    marco:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 4, 0)
    marco:Show()
end

-- Al abrir la casa vuelve, aunque la hubieras cerrado en la visita anterior.
local eventos = CreateFrame("Frame")
eventos:RegisterEvent("AUCTION_HOUSE_SHOW")
eventos:RegisterEvent("AUCTION_HOUSE_CLOSED")
eventos:RegisterEvent("ITEM_DATA_LOAD_RESULT")
eventos:SetScript("OnEvent", function(_, evento)
    if evento == "AUCTION_HOUSE_SHOW" then
        ocultaAdrede = false
    end
    V.Refrescar()
end)
