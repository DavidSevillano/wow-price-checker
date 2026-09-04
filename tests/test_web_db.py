import sqlite3

from web.db import abrir, aplicar_esquema


def test_abrir_crea_las_tablas(tmp_path):
    con = abrir(tmp_path / "prueba.db")
    tablas = {
        fila[0]
        for fila in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"precio", "estadistica", "reino", "nombre", "pagina", "volcado"} <= tablas


def test_abrir_deja_la_base_en_wal(tmp_path):
    con = abrir(tmp_path / "prueba.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_las_filas_salen_como_diccionarios(tmp_path):
    con = abrir(tmp_path / "prueba.db")
    con.execute("INSERT INTO reino (id, slug, nombre) VALUES (1305, 'kazzak', 'Kazzak')")
    fila = con.execute("SELECT * FROM reino").fetchone()
    assert fila["nombre"] == "Kazzak"


def test_aplicar_esquema_es_idempotente(tmp_path):
    ruta = tmp_path / "prueba.db"
    con = abrir(ruta)
    aplicar_esquema(con)
    aplicar_esquema(con)
    assert con.execute("SELECT count(*) FROM reino").fetchone()[0] == 0
