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
