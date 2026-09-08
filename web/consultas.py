"""Lecturas de la web pública. Funciones puras sobre una conexión."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Optional

from web.ingesta import SIN_VARIANTE

log = logging.getLogger("web.consultas")

# Cuántos reinos ve quien no paga. El corte se aplica aquí, en la consulta, y
# no en la plantilla: lo que no se pregunta no se envía, así que no queda nada
# en el HTML que se pueda descubrir quitando un estilo.
REINOS_GRATIS = 5

# A partir de cuántos reinos una mediana significa "lo que cuesta
# normalmente". Por debajo no es un precio típico: con dos reinos es el más
# caro de los dos, y con uno es el único precio que existe. La ficha no puede
# presentar eso como el precio normal, porque no lo sabe.
#
# No es un caso raro. En una base de dos reinos, 5.034 de 16.239 productos
# tenían datos de un solo reino; en la región entera son menos --269 de
# 20.144-- pero siguen siendo cientos de páginas afirmando lo que no consta.
#
# `productos_de_reino` ya tiene este mismo guardia con su propio umbral (15),
# y por la misma razón: no comparar contra una mediana que no significa nada.
REINOS_PARA_MEDIANA = 5

# Cuántos reinos hacen falta para que "está rebajado respecto a lo normal"
# signifique algo. Es un listón más alto que `REINOS_PARA_MEDIANA` porque aquí
# la mediana no se enseña, se usa para ordenar: una mediana floja no confunde
# a nadie, pero sí llena la portada y la página de reino de productos que solo
# existen en cuatro sitios y cuya "rebaja" es ruido.
#
# El valor es el de producción, con 92 reinos en la región. Se pasa como
# parámetro y no se lee dentro de las consultas para que los tests con una
# región de juguete puedan bajarlo sin tocar el criterio real.
REINOS_PARA_COMPARAR = 15

IDIOMA_POR_DEFECTO = "en"


def ficha(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> Optional[dict[str, Any]]:
    """Cabecera del producto y sus variantes con estadísticas.

    Devuelve None si de ese producto no hay nada en el último volcado, que es
    lo que la ruta convierte en un 404.
    """
    variantes = []
    for fila in con.execute(
        "SELECT variante, mediana, minimo, maximo, reinos "
        "  FROM estadistica "
        " WHERE tipo = ? AND producto_id = ? "
        " ORDER BY variante",
        (tipo, producto_id),
    ):
        variante = dict(fila)
        # La decisión se toma aquí y no en la plantilla para poder probarla:
        # una condición escrita en Jinja no la cubre ningún test.
        variante["mediana_fiable"] = variante["reinos"] >= REINOS_PARA_MEDIANA
        variantes.append(variante)

    if not variantes:
        return None

    fila = con.execute(
        "SELECT nombre, icono FROM nombre "
        " WHERE tipo = ? AND producto_id = ? AND idioma = ?",
        (tipo, producto_id, idioma),
    ).fetchone()

    # Si `volcado` está vacío la base quedó inconsistente (no es el camino
    # normal, porque `volcar` escribe precio y volcado en la misma
    # transacción): mejor una ficha sin fecha que un 500 para quien la ve.
    volcado = con.execute("SELECT generado_en FROM volcado").fetchone()

    return {
        "tipo": tipo,
        "producto_id": producto_id,
        "nombre": fila["nombre"] if fila else f"#{producto_id}",
        "icono": fila["icono"] if fila else None,
        "variantes": variantes,
        "generado_en": volcado[0] if volcado else None,
    }


def reinos_de(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    variante: Optional[int],
    limite: Optional[int] = REINOS_GRATIS,
) -> list[dict[str, Any]]:
    """Los reinos con existencias, del más barato al más caro.

    Con `limite=None` salen todos, que es lo que verá el plan de pago en v3.
    """
    sql = (
        "SELECT r.nombre, r.slug, p.minimo, p.listados "
        "  FROM precio p JOIN reino r ON r.id = p.reino_id "
        " WHERE p.tipo = ? AND p.producto_id = ? AND p.variante = ? "
        " ORDER BY p.minimo"
    )
    args: list[Any] = [
        tipo,
        producto_id,
        SIN_VARIANTE if variante is None else variante,
    ]
    if limite is not None:
        sql += " LIMIT ?"
        args.append(limite)

    return [dict(fila) for fila in con.execute(sql, args)]


def anotar_peticion(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    ahora: Optional[int] = None,
) -> None:
    """Deja constancia de que alguien ha pedido esta página.

    De aquí sale qué páginas existen de verdad: en vez de publicar las 20.144
    el primer día --que es el patrón que Google trata como contenido
    generado--, el índice crece con la demanda que ya hay.

    Esto es contabilidad, no contenido: si falla --un bloqueo agotado, el
    disco lleno, la base en solo lectura-- perder esta cuenta no vale nada,
    pero perder la página (que ya tiene todo lo que `ficha` y `reinos_de`
    necesitaban) sí. Por eso el fallo se traga aquí y no sube a quien llama.
    """
    try:
        con.execute(
            "INSERT INTO pagina (tipo, producto_id, primera_peticion) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(tipo, producto_id) DO UPDATE SET "
            "peticiones = peticiones + 1",
            (tipo, producto_id, ahora if ahora is not None else int(time.time())),
        )
    except sqlite3.Error:
        log.warning(
            "No se pudo anotar la petición de %s %s", tipo, producto_id, exc_info=True
        )


def reino_por_slug(con: sqlite3.Connection, slug: str) -> Optional[dict[str, Any]]:
    """El reino de esa URL, o None si el slug no existe (lo convierte en 404)."""
    fila = con.execute("SELECT * FROM reino WHERE slug = ?", (slug,)).fetchone()
    return dict(fila) if fila else None


def productos_de_reino(
    con: sqlite3.Connection,
    reino_id: int,
    limite: int,
    reinos_minimos: int = REINOS_PARA_COMPARAR,
) -> list[dict[str, Any]]:
    """Lo más rebajado del reino: donde más se separa del precio normal.

    Ordenar por precio a secas sacaría la lista de lo más caro, que no le
    interesa a nadie. Lo que se busca es dónde este reino está barato respecto
    a la región.

    Se exige `e.reinos >= reinos_minimos` para no llenar la página de
    productos que solo existen en un puñado de reinos, donde la mediana no
    significa nada: ver `REINOS_PARA_COMPARAR`, que es el mismo listón que
    usa `mejores_rebajas` para la portada.

    Coste medido en producción (92 reinos, 20.144 productos, 787.880 filas en
    `precio`): ~27 ms por vista de página de reino, frente a ~0,028 ms de las
    consultas de la página de producto. Se probó un índice en
    precio(reino_id, tipo, producto_id, variante) y se descartó: la lectura
    solo bajaba un 12% (26,8 ms → 23,6 ms) porque el coste está en el JOIN por
    fila contra `estadistica` y `nombre`, no en el acceso a `precio`; a cambio
    la pasada horaria que reescribe la tabla se volvía un 85% más lenta
    (1,37 s → 2,53 s). El arreglo de verdad es precalcular las filas rebajadas
    durante esa misma pasada en una tabla pequeña indexada por reino, pero eso
    queda fuera de v1.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT n.nombre, p.producto_id, p.variante, p.minimo, e.mediana "
            "  FROM precio p "
            "  JOIN estadistica e ON e.tipo = p.tipo "
            "                    AND e.producto_id = p.producto_id "
            "                    AND e.variante = p.variante "
            "  LEFT JOIN nombre n ON n.tipo = p.tipo "
            "                    AND n.producto_id = p.producto_id "
            "                    AND n.idioma = ? "
            " WHERE p.reino_id = ? AND e.reinos >= ? AND p.minimo < e.mediana "
            " ORDER BY CAST(p.minimo AS REAL) / e.mediana "
            " LIMIT ?",
            (IDIOMA_POR_DEFECTO, reino_id, reinos_minimos, limite),
        )
    ]


def paginas_mas_pedidas(con: sqlite3.Connection, limite: int) -> list[dict[str, Any]]:
    """Para el sitemap: solo entra lo que la gente busca de verdad.

    `limite` es obligatorio a propósito: un valor por defecto que nadie usa es
    una trampa para el próximo llamante que se olvide de pasarlo, y un
    sitemap truncado en silencio no se nota hasta que Google deja de indexar
    páginas que ya nadie le está diciendo que existen.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT tipo, producto_id, peticiones FROM pagina "
            " ORDER BY peticiones DESC, producto_id LIMIT ?",
            (limite,),
        )
    ]


def reinos_publicados(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Los reinos que cubre el sitio, en orden alfabético.

    La usan la portada, para enseñarlos, y el sitemap, para anunciarlos. Es la
    misma lista y sale de un solo sitio: dos SELECT parecidos en dos ficheros
    se separan en cuanto uno de los dos aprenda a filtrar algo.

    Alfabético y no por id porque la portada es una lista para buscar el reino
    propio, no un ranking: el id de reino conectado no significa nada para
    quien lee.
    """
    return [
        dict(fila)
        for fila in con.execute("SELECT nombre, slug FROM reino ORDER BY nombre")
    ]


def productos_mas_vistos(
    con: sqlite3.Connection, limite: int, idioma: str = IDIOMA_POR_DEFECTO
) -> list[dict[str, Any]]:
    """Los productos más pedidos, con su nombre, para enlazar desde la portada.

    Es `paginas_mas_pedidas` con el nombre puesto y con un filtro más: al
    sitemap le basta el id, pero una lista de enlaces necesita algo que leer y,
    sobre todo, no puede llevar a un 404.

    Ese es el `EXISTS`: `pagina` es un histórico y no se poda nunca --es de
    donde sale qué páginas existen de verdad--, mientras que `estadistica` se
    reescribe entera en cada pasada. Un objeto que Blizzard retire, o que
    simplemente deje de tener subastas en toda la región, se queda en `pagina`
    con sus peticiones intactas mientras su ficha ya responde 404. Enlazarlo
    desde la portada sería mandar a los rastreadores justo a donde no hay nada.

    El `EXISTS` y no un JOIN contra `estadistica` porque ahí hay una fila por
    ilvl: las Grebas tienen ocho variantes y saldrían ocho veces en la lista.

    `limite` es obligatorio, igual que en `paginas_mas_pedidas` y por lo mismo.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT g.tipo, g.producto_id, n.nombre, g.peticiones "
            "  FROM pagina g "
            "  LEFT JOIN nombre n ON n.tipo = g.tipo "
            "                    AND n.producto_id = g.producto_id "
            "                    AND n.idioma = ? "
            " WHERE EXISTS (SELECT 1 FROM estadistica e "
            "                WHERE e.tipo = g.tipo "
            "                  AND e.producto_id = g.producto_id) "
            " ORDER BY g.peticiones DESC, g.producto_id "
            " LIMIT ?",
            (idioma, limite),
        )
    ]


def mejores_rebajas(
    con: sqlite3.Connection,
    limite: int,
    reinos_minimos: int = REINOS_PARA_COMPARAR,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> list[dict[str, Any]]:
    """Lo más rebajado de toda la región, venga del reino que venga.

    Es la hermana de `productos_de_reino` con la pregunta al revés: allí es
    "qué está barato en MI reino" y aquí "dónde hay una ganga ahora mismo".
    Por eso cada fila trae su reino y su slug: sin eso la cifra no sirve de
    nada, porque no dice adónde ir a comprarlo.

    El corte es `<` y no `<=`: un reino que clava el precio normal no está
    rebajado, y con noventa y dos reinos los empates en la mediana son
    muchos.

    **Es cara: 271 ms medidos sobre 932.000 filas de `precio`**, contra los
    ~23 ms de la página de reino, porque aquí no hay un `reino_id` que recorte
    el escaneo y el `ORDER BY` se resuelve con un b-tree temporal sobre todo
    lo que pasa el filtro. Quien la llame en una ruta tiene que cachearla; la
    portada lo hace contra `volcado.generado_en`.
    """
    filas = []
    for fila in con.execute(
        "SELECT n.nombre, p.producto_id, p.variante, p.minimo, e.mediana, "
        "       r.nombre AS reino, r.slug "
        "  FROM precio p "
        "  JOIN estadistica e ON e.tipo = p.tipo "
        "                    AND e.producto_id = p.producto_id "
        "                    AND e.variante = p.variante "
        "  JOIN reino r ON r.id = p.reino_id "
        "  LEFT JOIN nombre n ON n.tipo = p.tipo "
        "                    AND n.producto_id = p.producto_id "
        "                    AND n.idioma = ? "
        " WHERE e.reinos >= ? AND p.minimo < e.mediana "
        " ORDER BY CAST(p.minimo AS REAL) / e.mediana "
        " LIMIT ?",
        (idioma, reinos_minimos, limite),
    ):
        rebaja = dict(fila)
        # El porcentaje se calcula aquí y no en la plantilla por lo mismo que
        # `mediana_fiable`: una cuenta escrita en Jinja no la cubre un test.
        rebaja["descuento"] = round((1 - rebaja["minimo"] / rebaja["mediana"]) * 100)
        filas.append(rebaja)
    return filas


def resumen_del_catalogo(con: sqlite3.Connection) -> dict[str, Any]:
    """Cuánto cubre el sitio y de cuándo son los datos, para la portada.

    `COUNT(DISTINCT producto_id)` y no `COUNT(*)`: en `estadistica` hay una
    fila por ilvl, así que las Grebas con sus ocho variantes contarían como
    ocho objetos. Son uno.

    `generado_en` sale a None con la base recién creada, que es el estado
    normal hasta que termina la primera pasada; la portada lo dibuja como
    "todavía no hay datos" en vez de inventarse una fecha.
    """
    productos = con.execute(
        "SELECT count(DISTINCT producto_id) FROM estadistica"
    ).fetchone()[0]
    reinos = con.execute("SELECT count(*) FROM reino").fetchone()[0]
    volcado = con.execute("SELECT generado_en FROM volcado").fetchone()
    return {
        "productos": productos,
        "reinos": reinos,
        "generado_en": volcado[0] if volcado else None,
    }
