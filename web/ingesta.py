"""Del agregado en memoria a las filas de la base.

El agregado es lo que ya devuelve `wowalerts.mercado.agregar()`: para cada
producto, qué precio mínimo y cuántos listados hay en cada reino.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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


@contextmanager
def _transaccion(con: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE ... COMMIT, deshaciendo si algo revienta.

    `abrir()` deja la conexión en autocommit, así que las transacciones se
    abren y se cierran a mano. Esto lo usan todas las escrituras grandes del
    módulo, y repetir el bloque en cada una es como se acaba olvidando un
    ROLLBACK.
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


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
    # `precio` es WITHOUT ROWID: su clave primaria (tipo, producto_id,
    # variante, reino_id) es la clave de agrupamiento física de la tabla, no
    # un índice aparte sobre un rowid oculto. `filas_de_precio` recorre el
    # agregado en orden de reino, que no coincide con ese orden de clave, así
    # que cada INSERT sin ordenar busca en el btree y puede partir una página
    # en vez de simplemente añadir al final. Medido sobre este esquema: 200
    # 000 filas en orden de clave, 0.30 s; las mismas filas desordenadas,
    # 1.76 s (~6x). No lo "simplifiques" quitando este sort.
    filas.sort()

    with _transaccion(con):
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
    return len(filas)
