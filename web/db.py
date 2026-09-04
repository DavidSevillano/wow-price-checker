"""Conexión a la base de la web pública.

Una sola base SQLite en modo WAL. WAL importa: la pasada horaria reemplaza las
792.403 filas de `precio` dentro de una transacción, y sin WAL eso dejaría al
sitio sin responder durante el reemplazo. Con WAL, quien esté leyendo sigue
viendo los datos de la pasada anterior hasta que la nueva termina.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).parent / "esquema.sql"

# Por defecto junto al código; en el servidor se pasa la ruta a mano.
RUTA_POR_DEFECTO = Path("web.db")

# Cuánto espera una escritura a que se suelte el bloqueo antes de rendirse.
# El bloqueo de SQLite es de toda la base, no de una tabla, y la pasada horaria
# reemplaza las 792.403 filas de `precio` dentro de una sola transacción. Las
# escrituras pequeñas --contar la visita a una página-- tienen que aguantar esa
# espera en vez de reventar: el defecto de Python son 5 segundos, bastante menos
# de lo que tarda el reemplazo, y eso daría un error 500 una vez por hora.
ESPERA_BLOQUEO_SEGUNDOS = 30.0


def aplicar_esquema(con: sqlite3.Connection) -> None:
    """Crea lo que falte. Es idempotente: todo el DDL lleva IF NOT EXISTS."""
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    con.commit()


def abrir(
    ruta: Path | str = RUTA_POR_DEFECTO, esquema: bool = True
) -> sqlite3.Connection:
    """Abre la base, la deja en WAL y, si se pide, se asegura de que el esquema está.

    `esquema=False` se lo pasa la web en cada petición: el esquema ya está
    puesto al arrancar (una vez, en `crear_app`), y volver a comprobarlo con
    `executescript` --seis CREATE TABLE IF NOT EXISTS más un índice-- cuesta
    más que la propia consulta de la página (medido: ~0,15 ms del esquema
    contra ~0,028 ms de `ficha` + `reinos_de`). El valor por defecto sigue
    siendo True para no romper a quien no sabe que puede saltárselo: la
    ingesta y los tests de este módulo abren así.
    """
    # isolation_level=None es autocommit: cada execute() se confirma solo y
    # commit() no delimita nada aquí. Quien haga una transacción de verdad
    # (la pasada horaria, por ejemplo) la abre y la cierra ella misma con
    # BEGIN/COMMIT explícitos.
    con = sqlite3.connect(
        str(ruta), isolation_level=None, timeout=ESPERA_BLOQUEO_SEGUNDOS
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    # Sin esto, cada INSERT del volcado espera al disco y la pasada tarda
    # minutos en vez de segundos. NORMAL solo arriesga la última transacción
    # ante un corte de luz, y lo que se pierde se regenera en una hora.
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA foreign_keys = ON")
    if esquema:
        aplicar_esquema(con)
    return con
