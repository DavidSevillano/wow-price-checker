"""Del agregado en memoria a las filas de la base.

El agregado es lo que ya devuelve `wowalerts.mercado.agregar()`: para cada
producto, qué precio mínimo y cuántos listados hay en cada reino.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator, Mapping

from wowalerts.mercado import Clave, ResumenReino

# En la base, "no tiene variante" es -1 y no NULL: dos NULL no comparan iguales
# en un índice de SQLite, y la variante es parte de la identidad del producto.
SIN_VARIANTE = -1

Fila = tuple[str, int, int, int, int, int]


def filas_de_precio(
    agregado: Mapping[Clave, Mapping[int, ResumenReino]],
) -> Iterator[Fila]:
    """(tipo, producto_id, variante, reino_id, minimo, listados) por cada par."""
    for clave, por_reino in agregado.items():
        variante = SIN_VARIANTE if clave.variante is None else clave.variante
        for reino_id, resumen in por_reino.items():
            yield (
                clave.tipo,
                clave.id,
                variante,
                reino_id,
                resumen.minimo,
                resumen.listados,
            )


def volcar(
    con: sqlite3.Connection,
    agregado: Mapping[Clave, Mapping[int, ResumenReino]],
    generado_en: int,
) -> int:
    """Reemplaza la tabla de precios entera. Devuelve cuántas filas ha escrito.

    Todo dentro de una transacción: quien esté leyendo la web sigue viendo el
    volcado anterior hasta el COMMIT, y nunca una mezcla de los dos.
    """
    filas = list(filas_de_precio(agregado))

    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM precio")
        con.executemany(
            "INSERT INTO precio "
            "(tipo, producto_id, variante, reino_id, minimo, listados) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            filas,
        )
        con.execute(
            "INSERT INTO volcado (id, generado_en) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET generado_en = excluded.generado_en",
            (generado_en,),
        )
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return len(filas)
