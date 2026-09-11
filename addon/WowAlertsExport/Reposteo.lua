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
--  cuatro estados: "cancelar", "cancelando" (esperando AUCTION_CANCELED),
--  "devuelta" y "posteando" (esperando AUCTION_HOUSE_AUCTION_CREATED), y sale
--  de la cola cuando el juego crea la subasta (o cuando se olvida).

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

local function claveObjeto(itemID, ilvl)
    return tostring(itemID) .. ":" .. tostring(ilvl)
end

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

-- auctionID -> true: adelantadas que la busqueda de esta visita ha confirmado.
-- Cancelar cuesta el deposito, asi que no se cancela con datos de otra visita.
local confirmadas = {}

-- El mayor id de subasta propia visto en la ultima busqueda. Los ids crecen
-- con el tiempo: sirve solo para reconocer, al buscar, un posteo de la tecla
-- cuyo aviso de creacion nunca llego, comparando con el id apuntado al postear.
local maxIdVisto = 0

-- La lista de subastas propias llega por partes, y la primera respuesta tras
-- abrir la casa viene vacia (ver WowAlertsExport.lua). Buscar con la lista a
-- medias borraria de la cola lo que no apareciera, asi que hace falta haber
-- recibido la lista despues de abrir y que la casa lleve unos segundos abierta.
local SEGUNDOS_PARA_FIARSE = 5
local abiertaEn = nil     -- GetTime() al abrir la casa
local recibidasEn = nil   -- GetTime() de la ultima OWNED_AUCTIONS_UPDATED

local function subastasListas()
    return abiertaEn ~= nil and recibidasEn ~= nil and recibidasEn >= abiertaEn
        and GetTime() - abiertaEn >= SEGUNDOS_PARA_FIARSE
end

-- Si la respuesta a una busqueda no llega en este tiempo (mensaje perdido,
-- otra busqueda del juego o de otro addon por medio), se salta ese objeto en
-- esta visita sin tocar su cola.
local SEGUNDOS_DE_ESPERA = 10
local consulta = 0        -- numero de la ultima busqueda enviada

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
    local nuevas = {}   -- claveObjeto -> ids de subastas activas de ese objeto

    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        local itemKey = info and info.itemKey
        if info and info.auctionID and info.auctionID > maxIdVisto then
            maxIdVisto = info.auctionID
        end
        -- status 0 es activa. 1 es vendida y pendiente de cobro: no se toca.
        if info and info.status == 0 and (info.buyoutAmount or 0) > 0
            and itemKey and objetos[itemKey.itemID] then
            activas[info.auctionID] = true
            local ilvl = (info.itemLink and GetDetailedItemLevelInfo(info.itemLink)) or itemKey.itemLevel
            local grupo = anadirAGrupo(itemKey)
            grupo.mias[#grupo.mias + 1] = {
                auctionID = info.auctionID,
                buyout = info.buyoutAmount,
                itemID = itemKey.itemID,
                ilvl = ilvl,
            }
            local clave = claveObjeto(itemKey.itemID, ilvl)
            nuevas[clave] = nuevas[clave] or {}
            table.insert(nuevas[clave], { id = info.auctionID, buyout = info.buyoutAmount })
        end
    end

    -- Si hay una subasta activa de ese objeto posterior a `tope` y a `precio`
    -- que no haya servido ya para otra entrada.
    local usadas = {}
    local function hayUnaPosterior(clave, tope, precio)
        for _, s in ipairs(nuevas[clave] or {}) do
            if s.id > tope and s.buyout == precio and not usadas[s.id] then
                usadas[s.id] = true
                return true
            end
        end
        return false
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
        elseif e.estado == "devuelta" or e.estado == "posteando" then
            if e.estado == "posteando" and e.idTope
                and hayUnaPosterior(claveObjeto(e.itemID, e.ilvl), e.idTope, e.precio) then
                -- El posteo de la tecla si se creo aunque no llegara el aviso
                -- (o se acepto desde el aviso de Blizzard): hay una subasta tuya
                -- de ese objeto, posterior y a ese precio. Con lo devuelto no se
                -- hace: otra copia puesta a mano no dice nada de esta.
                table.remove(entradas, i)
            else
                -- Un posteo del que no llego respuesta vuelve a la fila.
                e.estado = "devuelta"
                local grupo = anadirAGrupo(e.itemKey)
                grupo.devueltas[#grupo.devueltas + 1] = e
            end
        end
    end
end

local function lanzarSiguiente()
    if esperando or not buscando() or not casaAbierta() then
        return
    end
    if not C_AuctionHouse.IsThrottledMessageSystemReady() then
        -- La casa limita las consultas seguidas. Se reintenta con
        -- AUCTION_HOUSE_THROTTLED_SYSTEM_READY.
        return
    end
    esperando = ordenGrupos[siguienteGrupo]
    consulta = consulta + 1
    local esta = consulta
    C_AuctionHouse.SendSearchQuery(
        grupos[esperando].itemKey,
        { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } },
        true
    )
    C_Timer.After(SEGUNDOS_DE_ESPERA, function()
        if esperando and consulta == esta then
            esperando = nil
            siguienteGrupo = siguienteGrupo + 1
            lanzarSiguiente()
            R.refrescarPanel()
        end
    end)
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
                confirmadas[m.auctionID] = true
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
--  El buzon y la bolsa
-- ---------------------------------------------------------------------------

local function buzonAbierto()
    return MailFrame ~= nil and MailFrame:IsShown()
end

-- El asunto de las cartas de subasta cancelada, como patron. Sale del texto
-- del propio juego para funcionar en cualquier idioma ("Subasta cancelada: %s").
local function patronCancelada()
    local formato = AUCTION_REMOVED_MAIL_SUBJECT or "Auction cancelled: %s"
    local escapado = (formato:gsub("[%^%$%(%)%.%[%]%*%+%-%?]", "%%%0"))
    return "^" .. (escapado:gsub("%%s", "(.+)")) .. "$"
end

-- Recorre la bolsa llamando a `fn(bolsa, hueco, info)` en cada copia de ese
-- objeto e ilvl. Si `fn` devuelve true, se para.
local function enLaBolsa(itemID, ilvl, fn)
    for bolsa = 0, NUM_BAG_SLOTS do
        for hueco = 1, C_Container.GetContainerNumSlots(bolsa) do
            local info = C_Container.GetContainerItemInfo(bolsa, hueco)
            if info and info.itemID == itemID
                and GetDetailedItemLevelInfo(info.hyperlink) == ilvl then
                if fn(bolsa, hueco, info) then
                    return
                end
            end
        end
    end
end

-- Si esa copia se puede poner a la venta. Una copia ligada tiene el mismo
-- objeto e ilvl pero no se puede subastar: contarla o elegirla dejaria la
-- entrada atascada. La funcion se consulta solo si existe.
local function sePuedeVender(bolsa, hueco)
    if C_Item and C_Item.IsBound then
        return not C_Item.IsBound(ItemLocation:CreateFromBagAndSlot(bolsa, hueco))
    end
    return true
end

local function copiasEnBolsa(itemID, ilvl)
    local n = 0
    enLaBolsa(itemID, ilvl, function(bolsa, hueco)
        if sePuedeVender(bolsa, hueco) then
            n = n + 1
        end
    end)
    return n
end

-- Cartas ya pedidas y aun sin respuesta: indice -> { clave, en }. Se olvidan
-- con los eventos del buzon o a los pocos segundos, por si una recogida falla
-- sin que el buzon cambie (bolsa llena).
local tomadas = {}
local SEGUNDOS_DE_TOMA = 3

local function tomaReciente(t)
    return t ~= nil and GetTime() - t.en < SEGUNDOS_DE_TOMA
end

local function hayTomasRecientes()
    for _, t in pairs(tomadas) do
        if tomaReciente(t) then
            return true
        end
    end
    return false
end

local function cartaPorRecoger()
    local patron = patronCancelada()
    for i = 1, (GetInboxNumItems()) do
        if not tomaReciente(tomadas[i]) then
            local _, _, _, asunto, _, _, _, tieneObjeto = GetInboxHeaderInfo(i)
            if tieneObjeto and asunto and asunto:match(patron) then
                local _, itemID = GetInboxItem(i, 1)
                -- El enlace del adjunto puede no estar cargado todavia: sin el
                -- no se sabe el ilvl, y esa carta se deja para otra pulsacion.
                local enlace = GetInboxItemLink(i, 1)
                local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
                if itemID and ilvl then
                    local clave = claveObjeto(itemID, ilvl)

                    local devueltas = 0
                    for _, e in ipairs(cola()) do
                        if e.estado == "devuelta" and claveObjeto(e.itemID, e.ilvl) == clave then
                            devueltas = devueltas + 1
                        end
                    end
                    local pedidas = 0
                    for _, otra in pairs(tomadas) do
                        if tomaReciente(otra) and otra.clave == clave then
                            pedidas = pedidas + 1
                        end
                    end

                    -- Sin entradas de ese objeto no hace falta mirar la bolsa:
                    -- con muchas cartas ajenas eso seria recorrerla por cada una.
                    if devueltas > 0 and devueltas > copiasEnBolsa(itemID, ilvl) + pedidas then
                        return i, clave
                    end
                end
            end
        end
    end
    return nil, nil
end

-- Segundos desde la cancelacion antes de dar por hecho que la carta ya ha
-- tenido tiempo de llegar.
local SEGUNDOS_PARA_QUE_LLEGUE_LA_CARTA = 60

-- Segundos que tiene que seguir faltando algo antes de olvidarlo: una carta
-- recogida a mano o por otro addon tarda un momento en llegar a la bolsa.
local SEGUNDOS_FALTANDO = 3

-- Devueltas cuyo objeto ya no esta ni en el buzon ni en la bolsa (se vendio,
-- se envio o se puso a mano): se olvidan, para que el boton no mande de la
-- casa al buzon y vuelta. Solo con el buzon abierto y entero cargado, con
-- todas las cartas de subastas canceladas legibles, pasado un rato desde la
-- cancelacion, y si sigue faltando unos segundos despues de verlo faltar.
local function olvidarSinCarta()
    if not buzonAbierto() then
        return
    end
    local mostradas, total = GetInboxNumItems()
    if mostradas ~= total then
        return
    end

    local patron = patronCancelada()
    local cartas = {}
    for i = 1, mostradas do
        local _, _, _, asunto, _, _, _, tieneObjeto = GetInboxHeaderInfo(i)
        if tieneObjeto and asunto and asunto:match(patron) then
            local _, itemID = GetInboxItem(i, 1)
            local enlace = GetInboxItemLink(i, 1)
            local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
            if not (itemID and ilvl) then
                return
            end
            local clave = claveObjeto(itemID, ilvl)
            cartas[clave] = (cartas[clave] or 0) + 1
        end
    end

    local ahora = time()
    local entradas = cola()
    local vistas = {}
    local pendiente = false
    for i = #entradas, 1, -1 do
        local e = entradas[i]
        if e.estado == "devuelta" and e.canceladaEn
            and ahora - e.canceladaEn > SEGUNDOS_PARA_QUE_LLEGUE_LA_CARTA then
            local clave = claveObjeto(e.itemID, e.ilvl)
            vistas[clave] = (vistas[clave] or 0) + 1
            if vistas[clave] > (cartas[clave] or 0) + copiasEnBolsa(e.itemID, e.ilvl) then
                if not e.faltaEn then
                    e.faltaEn = ahora
                    pendiente = true
                elseif ahora - e.faltaEn >= SEGUNDOS_FALTANDO then
                    table.remove(entradas, i)
                else
                    pendiente = true
                end
            else
                e.faltaEn = nil
            end
        end
    end

    if pendiente then
        -- Se vuelve a mirar pasado el margen, llegue o no otro evento.
        C_Timer.After(SEGUNDOS_FALTANDO, function()
            olvidarSinCarta()
            R.refrescarPanel()
        end)
    end
end

-- ---------------------------------------------------------------------------
--  La tecla
-- ---------------------------------------------------------------------------

-- Si esa entrada se puede cancelar ya: adelantada confirmada en esta visita y
-- que el juego deja cancelar. CanCancelAuction se consulta solo si existe: una
-- subasta con puja, por ejemplo, no se puede cancelar y no debe gastar
-- pulsaciones.
local function sePuedeCancelar(e)
    return e.estado == "cancelar" and confirmadas[e.auctionID]
        and (not C_AuctionHouse.CanCancelAuction or C_AuctionHouse.CanCancelAuction(e.auctionID))
end

local function primeraPorCancelar()
    for _, e in ipairs(cola()) do
        if sePuedeCancelar(e) then
            return e
        end
    end
    return nil
end

-- La primera devuelta con el precio al dia en esta visita y una copia libre y
-- vendible en la bolsa, y donde esta esa copia.
local function paraPostear()
    for _, e in ipairs(cola()) do
        if e.estado == "devuelta" and repasadas[e.auctionID] and e.precio then
            local sitio = nil
            enLaBolsa(e.itemID, e.ilvl, function(bolsa, hueco, info)
                if not info.isLocked and sePuedeVender(bolsa, hueco) then
                    local candidato = ItemLocation:CreateFromBagAndSlot(bolsa, hueco)
                    if not C_AuctionHouse.IsSellItemValid
                        or C_AuctionHouse.IsSellItemValid(candidato, false) then
                        sitio = candidato
                        return true
                    end
                end
            end)
            if sitio then
                return e, sitio
            end
        end
    end
    return nil, nil
end

-- Lo que falta por confirmar del ultimo PostItem, si el juego pidio
-- confirmacion. Confirmar tambien es una funcion protegida, asi que va en su
-- propia pulsacion.
local confirmacion = nil

-- Si en el hueco guardado sigue el mismo objeto. Entre postear y confirmar se
-- puede ordenar la bolsa, y confirmar leeria lo que haya ahora en ese hueco.
-- El ilvl se lee del enlace, igual que al buscar en la bolsa: otra funcion
-- podria dar otro numero y la confirmacion no llegaria nunca.
local function sigueEnSuSitio(c)
    if not (C_Item and C_Item.DoesItemExist) then
        return true
    end
    if not C_Item.DoesItemExist(c.sitio) or C_Item.GetItemID(c.sitio) ~= c.itemID then
        return false
    end
    local enlace = C_Item.GetItemLink(c.sitio)
    return enlace ~= nil and GetDetailedItemLevelInfo(enlace) == c.ilvl
end

-- La casa de Blizzard abre su propio aviso de precio al postear, y tapa la
-- ventana hasta que se cierra. Su boton de aceptar no confirma lo nuestro, asi
-- que en cuanto la confirmacion se usa o se descarta, el aviso sobra.
local function cerrarAvisoDePrecio()
    if StaticPopup_Visible and StaticPopup_Hide and StaticPopup_Visible("AUCTION_HOUSE_POST_WARNING") then
        StaticPopup_Hide("AUCTION_HOUSE_POST_WARNING")
    end
end

-- Hace UNA accion y devuelve cual ("buscar", "cancelar", "recoger", "postear",
-- "confirmar"), o nil si no habia nada que hacer. Nunca llama a mas de una
-- funcion protegida.
function R.Siguiente()
    local hecho = nil
    if casaAbierta() then
        if confirmacion then
            if C_AuctionHouse.IsThrottledMessageSystemReady() then
                local c = confirmacion
                confirmacion = nil
                local e = buscarEntrada(c.auctionID)
                if sigueEnSuSitio(c) then
                    if e then
                        e.posteandoEn = GetTime()
                    end
                    C_AuctionHouse.ConfirmPostItem(c.sitio, c.duracion, 1, nil, c.precio)
                    hecho = "confirmar"
                elseif e and e.estado == "posteando" then
                    -- No se confirma: vuelve a estar lista para postear.
                    e.estado = "devuelta"
                end
                cerrarAvisoDePrecio()
            end
        elseif not buscadoEnEstaVisita then
            if subastasListas() then
                empezarBusqueda()
                hecho = "buscar"
            end
        elseif not buscando() then
            -- Con la casa saturada de consultas, cancelar o postear podria
            -- perderse sin aviso: mejor no hacer nada y que se vuelva a pulsar.
            local listo = C_AuctionHouse.IsThrottledMessageSystemReady()
            local e = primeraPorCancelar()
            if e then
                if listo then
                    C_AuctionHouse.CancelAuction(e.auctionID)
                    e.estado = "cancelando"
                    e.cancelandoEn = GetTime()
                    hecho = "cancelar"
                end
            elseif listo then
                local d, sitio = paraPostear()
                if d then
                    local duracion = vigilados().duracion
                    -- La entrada sale de la cola cuando el juego crea la subasta
                    -- (AUCTION_HOUSE_AUCTION_CREATED), no al pedirlo: un posteo
                    -- rechazado, o aceptado desde el aviso de Blizzard, dejaria
                    -- la cola descuadrada. Se marca antes de llamar porque ese
                    -- evento puede llegar enseguida.
                    d.estado = "posteando"
                    d.posteandoEn = GetTime()
                    d.idTope = maxIdVisto
                    if C_AuctionHouse.PostItem(sitio, duracion, 1, nil, d.precio) then
                        confirmacion = {
                            sitio = sitio,
                            duracion = duracion,
                            precio = d.precio,
                            auctionID = d.auctionID,
                            itemID = d.itemID,
                            ilvl = d.ilvl,
                        }
                    end
                    hecho = "postear"
                end
            end
        end
    elseif buzonAbierto() then
        local indice, clave = cartaPorRecoger()
        if indice then
            TakeInboxItem(indice, 1)
            tomadas[indice] = { clave = clave, en = GetTime() }
            hecho = "recoger"
        end
    end
    R.refrescarPanel()
    return hecho
end

-- ---------------------------------------------------------------------------
--  El panel
-- ---------------------------------------------------------------------------
--  Un boton debajo de la casa o del buzon que dice que va a hacer la tecla.
--  Pulsarlo es lo mismo que pulsar la tecla asignada.

BINDING_HEADER_WOWALERTS = "WoW Alerts"
BINDING_NAME_WOWALERTS_SIGUIENTE = "Reposteo: siguiente paso"

local function contar(estadoBuscado)
    local n = 0
    for _, e in ipairs(cola()) do
        if e.estado == estadoBuscado then
            n = n + 1
        end
    end
    return n
end

local function devueltaEnBolsa()
    for _, e in ipairs(cola()) do
        if e.estado == "devuelta" and copiasEnBolsa(e.itemID, e.ilvl) > 0 then
            return true
        end
    end
    return false
end

local function contarCancelables()
    local n = 0
    for _, e in ipairs(cola()) do
        if sePuedeCancelar(e) then
            n = n + 1
        end
    end
    return n
end

-- Adelantadas que la busqueda de esta visita no ha podido confirmar.
local function sinConfirmar()
    for _, e in ipairs(cola()) do
        if e.estado == "cancelar" and not confirmadas[e.auctionID] then
            return true
        end
    end
    return false
end

-- Segundos tras los que una cancelacion o un posteo sin respuesta se da por
-- atascado: el boton deja de decir que espera y pide volver a buscar.
local SEGUNDOS_SIN_RESPUESTA = 10

local function hayReciente(estadoBuscado, campo)
    for _, e in ipairs(cola()) do
        if e.estado == estadoBuscado and e[campo]
            and GetTime() - e[campo] < SEGUNDOS_SIN_RESPUESTA then
            return true
        end
    end
    return false
end

local function hayAtascada()
    for _, e in ipairs(cola()) do
        if e.estado == "cancelando" or e.estado == "posteando" then
            local desde
            if e.estado == "cancelando" then
                desde = e.cancelandoEn
            else
                desde = e.posteandoEn
            end
            if not desde or GetTime() - desde >= SEGUNDOS_SIN_RESPUESTA then
                return true
            end
        end
    end
    return false
end

function R.Estado()
    if confirmacion then
        return "Confirmar posteo"
    end
    if casaAbierta() then
        if not buscadoEnEstaVisita then
            if subastasListas() then
                return "Buscar undercuts"
            end
            return "Leyendo tus subastas..."
        end
        if buscando() then
            return ("Buscando %s/%s..."):format(siguienteGrupo, #ordenGrupos)
        end
        if primeraPorCancelar() then
            return ("Cancelar (%s)"):format(contarCancelables())
        end
        if paraPostear() then
            return "Postear"
        end
        if hayReciente("cancelando", "cancelandoEn") then
            return "Cancelando..."
        end
        if hayReciente("posteando", "posteandoEn") then
            return "Posteando..."
        end
        if sinConfirmar() or devueltaEnBolsa() or hayAtascada() then
            -- Hay algo cuyo precio no se ha podido repasar en esta visita.
            return "Cierra y abre la casa para repasar precios"
        end
        if contar("devuelta") > 0 then
            return "Recoge lo devuelto en el buzon"
        end
        return "Nada que repostear"
    end
    if buzonAbierto() then
        if cartaPorRecoger() then
            return "Recoger del buzon"
        end
        if contar("devuelta") > 0 then
            return "Vuelve a la casa a postear"
        end
        return "Nada que recoger"
    end
    return "Nada que repostear"
end

local boton = nil

local function colocarBoton(padre)
    if not padre then
        return
    end
    if not boton then
        boton = CreateFrame("Button", "WowAlertsReposteoBoton", padre, "UIPanelButtonTemplate")
        boton:SetSize(280, 24)
        boton:SetScript("OnClick", function()
            R.Siguiente()
        end)
    end
    boton:SetParent(padre)
    boton:ClearAllPoints()
    boton:SetPoint("TOP", padre, "BOTTOM", 0, -4)
    boton:Show()
end

function R.refrescarPanel()
    -- La interfaz de la casa se carga bajo demanda: si al abrir aun no existia,
    -- el boton se coloca en el siguiente refresco.
    if casaAbierta() and (not boton or boton:GetParent() ~= AuctionHouseFrame) then
        colocarBoton(AuctionHouseFrame)
    elseif buzonAbierto() and (not boton or boton:GetParent() ~= MailFrame) then
        colocarBoton(MailFrame)
    end
    if not casaAbierta() and not buzonAbierto() then
        -- Con las dos ventanas cerradas el boton no se ve: no hace falta
        -- recalcular nada, y BAG_UPDATE_DELAYED llega a menudo.
        return
    end
    if not boton then
        return
    end
    boton:SetText(R.Estado())
    if buscando() then
        boton:Disable()
    else
        boton:Enable()
    end
end

-- ---------------------------------------------------------------------------
--  Eventos
-- ---------------------------------------------------------------------------

local frame = CreateFrame("Frame")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("ITEM_SEARCH_RESULTS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
frame:RegisterEvent("OWNED_AUCTIONS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
frame:RegisterEvent("AUCTION_CANCELED")
frame:RegisterEvent("AUCTION_HOUSE_AUCTION_CREATED")
frame:RegisterEvent("MAIL_SHOW")
frame:RegisterEvent("MAIL_CLOSED")
frame:RegisterEvent("MAIL_INBOX_UPDATE")
frame:RegisterEvent("BAG_UPDATE_DELAYED")

frame:SetScript("OnEvent", function(_, evento, arg1)
    if evento == "AUCTION_HOUSE_SHOW" then
        abiertaEn = GetTime()
        buscadoEnEstaVisita = false
        repasadas = {}
        confirmadas = {}
        reiniciarBusqueda()
        colocarBoton(AuctionHouseFrame)
        -- Pasada la espera no llega ningun evento: se refresca a mano para que
        -- el boton deje de decir "Leyendo tus subastas...".
        C_Timer.After(SEGUNDOS_PARA_FIARSE, function()
            R.refrescarPanel()
        end)
    elseif evento == "AUCTION_HOUSE_CLOSED" then
        abiertaEn = nil
        if confirmacion then
            local e = buscarEntrada(confirmacion.auctionID)
            if e and e.estado == "posteando" then
                e.estado = "devuelta"
            end
        end
        confirmacion = nil
        reiniciarBusqueda()
    elseif evento == "OWNED_AUCTIONS_UPDATED" then
        recibidasEn = GetTime()
    elseif evento == "ITEM_SEARCH_RESULTS_UPDATED" then
        alResponder(arg1)
    elseif evento == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
        lanzarSiguiente()
    elseif evento == "AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED" then
        -- El servidor ha descartado una consulta: se vuelve a pedir la que
        -- estaba en curso.
        esperando = nil
        lanzarSiguiente()
    elseif evento == "AUCTION_CANCELED" then
        -- arg1 es el id de la subasta. El exportador apunta la cancelacion por
        -- su cuenta, con su propio frame.
        local e = buscarEntrada(arg1)
        if e and (e.estado == "cancelando" or e.estado == "cancelar") then
            e.estado = "devuelta"
            e.canceladaEn = time()
        end
    elseif evento == "AUCTION_HOUSE_AUCTION_CREATED" then
        local entradas = cola()
        if confirmacion then
            -- Se acepto desde el aviso de Blizzard: la subasta creada es la que
            -- esperaba confirmacion.
            local _, i = buscarEntrada(confirmacion.auctionID)
            if i then
                table.remove(entradas, i)
            end
            confirmacion = nil
            cerrarAvisoDePrecio()
        else
            -- La mas reciente de las que se estan posteando, si es de hace un
            -- momento. Una subasta creada mucho despues es otra cosa, como un
            -- posteo a mano: de los posteos viejos se encarga la busqueda.
            local elegida, reciente = nil, nil
            for i, e in ipairs(entradas) do
                if e.estado == "posteando" and e.posteandoEn
                    and GetTime() - e.posteandoEn < SEGUNDOS_SIN_RESPUESTA
                    and (not reciente or e.posteandoEn >= reciente) then
                    elegida, reciente = i, e.posteandoEn
                end
            end
            if elegida then
                table.remove(entradas, elegida)
            end
        end
    elseif evento == "MAIL_SHOW" or evento == "MAIL_CLOSED" or evento == "MAIL_INBOX_UPDATE" then
        -- Justo despues de recoger, la carta ya no esta y el objeto puede no
        -- haber llegado a la bolsa: ese momento no sirve para olvidar nada.
        if evento == "MAIL_INBOX_UPDATE" and not hayTomasRecientes() then
            olvidarSinCarta()
        end
        tomadas = {}
        if evento == "MAIL_SHOW" then
            colocarBoton(MailFrame)
        end
    elseif evento == "BAG_UPDATE_DELAYED" then
        olvidarSinCarta()
    end
    R.refrescarPanel()
end)
