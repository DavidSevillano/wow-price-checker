-- La ventana "Tus subastas": que tienes puesto y que te han adelantado.
--
-- Solo dibuja. Quien clasifica es WowAlertsReposteo.Subastas(), y quien manda
-- redibujar es R.refrescarPanel().

local V = {}
WowAlertsVentana = V

local ANCHO = 330
local ALTO_FILA = 34
local ALTO_TITULO = 18
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
    return tostring(math.floor(cobre / 10000)) .. " o"
end

-- Las subastas solo a puja no tienen buyout, ni el rival tiene por que
-- tenerlo: en vez de ensenar "0 o", que se entienda que no hay precio fijo.
local function precioTexto(cobre)
    if not cobre then
        return "solo puja"
    end
    return oro(cobre)
end

local function crearMarco()
    -- OJO: el nombre que se le da aqui a CreateFrame se convierte en un
    -- global (_G[nombre] = marco). Si se llamara "WowAlertsVentana", igual
    -- que la tabla del modulo de la linea 7, lo pisaria en cuanto se creara
    -- el marco por primera vez: WowAlertsVentana dejaria de ser esta tabla y
    -- pasaria a ser el Frame, que no tiene .Refrescar. A partir de ahi
    -- Reposteo.lua nunca mas conseguiria avisar a la ventana, sin ningun
    -- error en pantalla. Por eso el marco lleva un nombre distinto, como
    -- hace Reposteo.lua con su boton (WowAlertsReposteoBoton).
    marco = CreateFrame("Frame", "WowAlertsVentanaMarco", UIParent, "BasicFrameTemplateWithInset")
    marco:SetSize(ANCHO, 200)
    marco:SetFrameStrata("HIGH")

    -- No es movible a proposito: cada Refrescar() la vuelve a anclar junto a
    -- la casa, asi que si se pudiera arrastrar volveria a su sitio en el
    -- primer evento y solo confundiria. El diseno no pide moverla.
    marco.CloseButton:HookScript("OnClick", function()
        -- Solo cuenta como "cerrada a proposito" si la cierra el usuario con
        -- este boton. AUCTION_HOUSE_CLOSED tambien la esconde, pero eso no
        -- activa ocultaAdrede: se resetea a false en AUCTION_HOUSE_SHOW para
        -- que vuelva a salir la proxima vez que abras la casa.
        ocultaAdrede = true
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

-- Una fila reutilizable: icono, nombre, detalle e ilvl. El mismo indice se
-- reusa a veces como titulo de grupo y a veces como fila de subasta entre un
-- Refrescar() y el siguiente, asi que quien la pinte tiene que dejarla en su
-- estado completo (alto, anclas, visibilidad de icono) sin dar nada por
-- puesto de la vez anterior.
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

-- Un titulo de grupo: mas bajo que una fila y con el texto pegado al borde,
-- no indentado como si colgara de un icono que ni siquiera se ve.
local function titulo(indice, texto, r, g, b)
    local f = fila(indice)
    f:SetHeight(ALTO_TITULO)
    f.icono:Hide()
    f.nombre:ClearAllPoints()
    f.nombre:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
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
    f:SetHeight(ALTO_FILA)
    f.nombre:ClearAllPoints()
    f.nombre:SetPoint("TOPLEFT", f.icono, "TOPRIGHT", 6, 0)

    -- GetOwnedAuctionInfo deja el enlace a nil en las mercancias (Reposteo.lua
    -- ya se protege de lo mismo). Sin enlace, GetItemInfo acepta el itemID.
    local nombre, _, calidad, _, _, _, _, _, _, icono = datosDelObjeto(datos.enlace or datos.itemID)
    f.icono:SetTexture(icono or "Interface\\Icons\\INV_Misc_QuestionMark")
    f.icono:Show()

    local r, g, b = colorDeCalidad(calidad or 1)
    -- Si colorDeCalidad no devuelve nada (calidad rara, cache a medias),
    -- que no reviente por un SetTextColor(nil).
    r, g, b = r or 1, g or 1, b or 1
    f.nombre:SetText(nombre or (datos.enlace or ("Objeto " .. tostring(datos.itemID))))
    f.nombre:SetTextColor(r, g, b)

    if datos.grupo == "adelantada" then
        if datos.igualada then
            f.detalle:SetText(("%s  |cffff4a3d> te igualan|r"):format(precioTexto(datos.precio)))
        else
            f.detalle:SetText(("%s  |cffff4a3d> rival %s|r"):format(
                precioTexto(datos.precio), precioTexto(datos.precioRival)))
        end
    else
        f.detalle:SetText(precioTexto(datos.precio))
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
            alto = alto + ALTO_TITULO
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

-- ITEM_DATA_LOAD_RESULT llega en rafagas (un evento por cada objeto que se
-- cachea) mientras algo como TSM o Auctionator esta escaneando. Se agrupan
-- los redibujados igual que revisionProgramada en Reposteo.lua: si ya hay
-- uno pendiente, no se programa otro.
local SEGUNDOS_AGRUPADOS = 0.2
local redibujoProgramado = false

local function pedirRedibujado()
    if redibujoProgramado then
        return
    end
    redibujoProgramado = true
    C_Timer.After(SEGUNDOS_AGRUPADOS, function()
        redibujoProgramado = false
        V.Refrescar()
    end)
end

local eventos = CreateFrame("Frame")
eventos:RegisterEvent("AUCTION_HOUSE_SHOW")
eventos:RegisterEvent("AUCTION_HOUSE_CLOSED")
eventos:RegisterEvent("ITEM_DATA_LOAD_RESULT")
eventos:SetScript("OnEvent", function(_, evento)
    if evento == "AUCTION_HOUSE_CLOSED" then
        -- Se decide por el evento, no mirando IsShown(): este marco se
        -- registra al cargar el addon, pero la ventana de Blizzard carga
        -- bajo demanda, asi que este manejador puede correr ANTES de que la
        -- suya desaparezca. Si aqui se mirara AuctionHouseFrame:IsShown(),
        -- saldria verdadero todavia y Refrescar() volveria a mostrar la
        -- ventana justo cuando la casa se cierra.
        if marco then
            marco:Hide()
        end
        return
    end
    if evento == "AUCTION_HOUSE_SHOW" then
        -- Al abrir la casa vuelve, aunque la hubieras cerrado en la visita
        -- anterior.
        ocultaAdrede = false
        V.Refrescar()
        return
    end
    pedirRedibujado()
end)
