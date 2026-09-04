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


def aplicar_esquema(con: sqlite3.Connection) -> None:
    """Crea lo que falte. Es idempotente: todo el DDL lleva IF NOT EXISTS."""
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    con.commit()


def abrir(ruta: Path | str = RUTA_POR_DEFECTO) -> sqlite3.Connection:
    """Abre la base, la deja en WAL y se asegura de que el esquema está."""
    con = sqlite3.connect(str(ruta), isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    # Sin esto, cada INSERT del volcado espera al disco y la pasada tarda
    # minutos en vez de segundos. NORMAL solo arriesga la última transacción
    # ante un corte de luz, y lo que se pierde se regenera en una hora.
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA foreign_keys = ON")
    aplicar_esquema(con)
    return con
