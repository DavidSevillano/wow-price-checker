"""Lecturas de la web pública. Funciones puras sobre una conexión."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from web.ingesta import SIN_VARIANTE

# Cuántos reinos ve quien no paga. El corte se aplica aquí, en la consulta, y
# no en la plantilla: lo que no se pregunta no se envía, así que no queda nada
# en el HTML que se pueda descubrir quitando un estilo.
REINOS_GRATIS = 5

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
    variantes = [
        dict(fila)
        for fila in con.execute(
            "SELECT variante, mediana, minimo, maximo, reinos "
            "  FROM estadistica "
            " WHERE tipo = ? AND producto_id = ? "
            " ORDER BY variante",
            (tipo, producto_id),
        )
    ]
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
