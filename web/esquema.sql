-- Precio más barato de cada producto en cada reino, tal y como estaba en el
-- último volcado. Se reemplaza entera en cada pasada: no hay histórico.
--
-- `variante` es el ilvl del equipo o la calidad de la mascota, y -1 en lo que
-- no escala. Se usa -1 y no NULL porque en un índice de SQLite dos NULL no
-- comparan iguales, y esto forma parte de la identidad del producto.
CREATE TABLE IF NOT EXISTS precio (
    tipo        TEXT    NOT NULL,
    producto_id INTEGER NOT NULL,
    variante    INTEGER NOT NULL,
    reino_id    INTEGER NOT NULL,
    minimo      INTEGER NOT NULL,
    listados    INTEGER NOT NULL,
    PRIMARY KEY (tipo, producto_id, variante, reino_id)
) WITHOUT ROWID;

-- Resumen por producto de todo lo anterior. Se recalcula en la misma pasada
-- para no tener que sacar medianas en cada visita.
CREATE TABLE IF NOT EXISTS estadistica (
    tipo        TEXT    NOT NULL,
    producto_id INTEGER NOT NULL,
    variante    INTEGER NOT NULL,
    mediana     INTEGER NOT NULL,
    minimo      INTEGER NOT NULL,
    maximo      INTEGER NOT NULL,
    reinos      INTEGER NOT NULL,
    PRIMARY KEY (tipo, producto_id, variante)
) WITHOUT ROWID;

-- `slug` es la URL de /realm/<slug>: `_slugs_unicos` en web/ingesta.py ya
-- garantiza que no se repita, pero el UNIQUE es la red de seguridad -- si
-- algún día ese código tuviera un bug, se ve como un IntegrityError al
-- guardar y no como un reino que calladamente deja de tener manera de
-- llegar a él.
CREATE TABLE IF NOT EXISTS reino (
    id     INTEGER PRIMARY KEY,
    slug   TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL
);

-- Nombre localizado e icono. El icono es del producto, no de la variante, así
-- que aquí no hay columna `variante`.
CREATE TABLE IF NOT EXISTS nombre (
    tipo        TEXT NOT NULL,
    producto_id INTEGER NOT NULL,
    idioma      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    icono       TEXT,
    PRIMARY KEY (tipo, producto_id, idioma)
) WITHOUT ROWID;

-- Qué páginas existen. Una página nace la primera vez que alguien la pide, no
-- el día del despliegue: publicar veinte mil páginas sin tráfico es justo el
-- patrón que Google trata como contenido generado.
CREATE TABLE IF NOT EXISTS pagina (
    tipo             TEXT    NOT NULL,
    producto_id      INTEGER NOT NULL,
    primera_peticion INTEGER NOT NULL,
    peticiones       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (tipo, producto_id)
) WITHOUT ROWID;

-- Cuándo se generó lo que hay ahora mismo en `precio`. Una sola fila.
CREATE TABLE IF NOT EXISTS volcado (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    generado_en INTEGER NOT NULL
);

-- Para "dame todos los reinos de este producto", que es la consulta de la
-- ficha y la única que se hace en caliente.
CREATE INDEX IF NOT EXISTS precio_por_producto
    ON precio (tipo, producto_id, variante, minimo);
