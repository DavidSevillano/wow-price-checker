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
    reinos_minimos: int = 15,
) -> list[dict[str, Any]]:
    """Lo más rebajado del reino: donde más se separa del precio normal.

    Ordenar por precio a secas sacaría la lista de lo más caro, que no le
    interesa a nadie. Lo que se busca es dónde este reino está barato respecto
    a la región.

    Se exige `e.reinos >= reinos_minimos` para no llenar la página de
    productos que solo existen en un puñado de reinos, donde la mediana no
    significa nada. El valor por defecto (15) es el de producción, con 92
    reinos en la región; `reinos_minimos` es un parámetro y no una constante
    interna para que los tests con una región de juguete (10 reinos en la
    fixture) puedan bajarlo sin tocar el criterio real.

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
