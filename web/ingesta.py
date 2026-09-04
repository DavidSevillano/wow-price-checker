"""Del agregado en memoria a las filas de la base.

El agregado es lo que ya devuelve `wowalerts.mercado.agregar()`: para cada
producto, qué precio mínimo y cuántos listados hay en cada reino.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from typing import Iterable, Iterator, Mapping

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


def recalcular_estadisticas(con: sqlite3.Connection) -> int:
    """Reconstruye `estadistica` (mediana, extremos, reinos) desde `precio`.

    Se corre una vez por pasada horaria para que la web nunca tenga que sacar
    una mediana al vuelo en una petición.

    La mediana no se interpola: tiene que ser un precio que exista de verdad
    en algún reino, porque se le enseña al usuario como "lo que cuesta
    normalmente" y un promedio entre dos reinos daría un número que no se
    cumple en ninguno. Con un número par de reinos se toma el de arriba de
    los dos del medio. Ordenando de menor a mayor y contando desde 0, esa
    posición es (n - 1) / 2 + (n - 1) % 2 (división entera): n=1→0, n=2→1,
    n=3→1, n=4→2, n=6→3.

    Ojo: esto NO es lo mismo que `wowalerts.mercado.percentil`, que redondea
    con round(0.5 * (n - 1)) (banker's rounding de Python). Para n par las
    dos fórmulas coinciden solo a veces -- n=4 da el mismo índice en las dos,
    pero n=6 da 3 aquí y 2 allá. Las dos garantizan un precio real, pero no
    son la misma regla.
    """
    # Se calcula con una CTE de funciones ventana en vez de una subconsulta
    # correlacionada: SQLite no deja usar el COUNT(*) de la consulta externa
    # dentro del OFFSET de una subconsulta correlacionada ("misuse of
    # aggregate function COUNT()"), así que hace falta ROW_NUMBER()/COUNT()
    # OVER (PARTITION BY ...) y quedarse con la fila en la posición calculada.
    with _transaccion(con):
        con.execute("DELETE FROM estadistica")
        con.execute(
            """
            INSERT INTO estadistica
                (tipo, producto_id, variante, mediana, minimo, maximo, reinos)
            WITH numerado AS (
                SELECT tipo, producto_id, variante, minimo,
                       ROW_NUMBER() OVER w AS orden,
                       COUNT(*)    OVER w AS reinos,
                       MIN(minimo) OVER w AS grupo_min,
                       MAX(minimo) OVER w AS grupo_max
                  FROM precio
                -- Una sola ventana para las cuatro funciones: con specs
                -- distintas (ROW_NUMBER con ORDER BY, las demás sin él)
                -- SQLite las resolvía en corrutinas separadas y metía un
                -- "USE TEMP B-TREE FOR ORDER BY" que ordenaba las 792 403
                -- filas dos veces. El ROWS BETWEEN ... es obligatorio: en
                -- cuanto la ventana lleva ORDER BY, el marco por defecto es
                -- "hasta la fila actual", y sin fijarlo entero COUNT/MIN/MAX
                -- pasarían de ver toda la partición a ir acumulando fila a
                -- fila (reinos contando hacia arriba, minimo == maximo ==
                -- mediana).
                WINDOW w AS (
                    PARTITION BY tipo, producto_id, variante ORDER BY minimo
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            )
            -- La fila que cae en la posición `orden` es la mediana (por eso
            -- su `minimo` de partida pasa a la columna `mediana` del
            -- INSERT); `grupo_min`/`grupo_max` son el mínimo y el máximo de
            -- todo el grupo, no de esa fila.
            SELECT tipo, producto_id, variante, minimo, grupo_min, grupo_max, reinos
              FROM numerado
             -- `orden` es 1-indexado (ROW_NUMBER), pero la fórmula de la
             -- mediana en el docstring está en base 0: el +1 de aquí es lo
             -- que hace la conversión, no lo quites si tocas esto.
             WHERE orden = (reinos - 1) / 2 + (reinos - 1) % 2 + 1
            """
        )
        (filas,) = con.execute("SELECT COUNT(*) FROM estadistica").fetchone()
    return filas


def slug(texto: str) -> str:
    """Nombre de reino a fragmento de URL: "Zul'jin / Uldum" -> "zuljin-uldum".

    Normaliza a NFKD, se queda solo con ASCII, pasa a minúsculas, quita los
    apóstrofos (para que "Zul'jin" salga "zuljin" y no "zul-jin") y colapsa
    cualquier tirada de los caracteres que queden que no sean letras o
    dígitos en un solo guion, sin guiones sobrantes al principio o al final.

    Puede devolver "" de verdad: un nombre enteramente en cirílico (hay
    reinos así en EU, p.ej. "Гордунни") no tiene ninguna letra ASCII que
    sobreviva al filtro. Esta función no lo resuelve -- decidir qué hacer con
    ese caso vacío es cosa de quien la llama (`guardar_reinos` cae al id).
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    solo_ascii = descompuesto.encode("ascii", errors="ignore").decode("ascii")
    minusculas = solo_ascii.lower()
    sin_apostrofos = minusculas.replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", sin_apostrofos).strip("-")


def guardar_reinos(con: sqlite3.Connection, nombres: Mapping[int, str]) -> None:
    """Upsert de id de reino -> nombre y slug.

    EU tiene reinos con el nombre enteramente en cirílico (p.ej. "Гордунни",
    "Свежеватель Душ", "Ревущий фьорд"): `slug()` les da "" porque no les
    queda ni una letra ASCII. Si se guardara ese "" tal cual, los tres
    reinos compartirían slug y `/realm/<slug>` no sabría a cuál de ellos
    servir. Por eso, cuando el slug sale vacío, se usa el id del reino como
    slug de repuesto -- es feo pero es único de por sí, sin depender de una
    librería de transliteración.
    """
    filas = []
    for reino_id, nombre in nombres.items():
        slug_calculado = slug(nombre) or str(reino_id)
        filas.append((reino_id, slug_calculado, nombre))

    with _transaccion(con):
        con.executemany(
            "INSERT INTO reino (id, slug, nombre) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET slug = excluded.slug, "
            "nombre = excluded.nombre",
            filas,
        )


def guardar_nombres(
    con: sqlite3.Connection,
    filas: Iterable[tuple[str, int, str, str, str | None]],
) -> None:
    """Upsert de (tipo, producto_id, idioma) -> nombre localizado e icono.

    La API de Blizzard trae el nombre de cada objeto en ocho idiomas sin
    coste extra, y eso multiplica gratis la superficie de búsqueda del
    sitio: cada idioma es una entrada más por la que se puede encontrar el
    mismo producto.
    """
    with _transaccion(con):
        con.executemany(
            "INSERT INTO nombre (tipo, producto_id, idioma, nombre, icono) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tipo, producto_id, idioma) DO UPDATE SET "
            "nombre = excluded.nombre, icono = excluded.icono",
            filas,
        )
