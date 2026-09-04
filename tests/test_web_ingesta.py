import sqlite3

import pytest

from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino
from web.db import abrir
from web.ingesta import (
    SIN_VARIANTE,
    filas_de_precio,
    guardar_nombres,
    guardar_reinos,
    recalcular_estadisticas,
    slug,
    volcar,
)


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


def test_una_fila_por_producto_y_reino():
    agregado = {
        Clave(TIPO_OBJETO, 271440, 305): {
            1305: resumen(500_000_000),
            1329: resumen(700_000_000, 900_000_000),
        }
    }
    filas = sorted(filas_de_precio(agregado))
    assert filas == [
        (TIPO_OBJETO, 271440, 305, 1305, 500_000_000, 1),
        (TIPO_OBJETO, 271440, 305, 1329, 700_000_000, 2),
    ]


def test_lo_que_no_escala_se_guarda_como_menos_uno():
    agregado = {Clave(TIPO_OBJETO, 258126, None): {1305: resumen(600_000_000)}}
    assert list(filas_de_precio(agregado))[0][2] == SIN_VARIANTE


def test_las_mascotas_conservan_su_tipo():
    agregado = {Clave(TIPO_MASCOTA, 303, 3): {1305: resumen(100_000_000)}}
    assert list(filas_de_precio(agregado))[0][0] == TIPO_MASCOTA


def test_volcar_deja_las_filas_en_la_base(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}}
    volcar(con, agregado, generado_en=1788451184)

    fila = con.execute("SELECT * FROM precio").fetchone()
    assert fila["producto_id"] == 271440
    assert fila["minimo"] == 500_000_000
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 1788451184


def test_volcar_reemplaza_lo_anterior(tmp_path):
    con = abrir(tmp_path / "p.db")
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1305: resumen(100)}}, generado_en=1)
    volcar(con, {Clave(TIPO_OBJETO, 2, 305): {1305: resumen(200)}}, generado_en=2)

    filas = con.execute("SELECT producto_id FROM precio").fetchall()
    assert [f[0] for f in filas] == [2]
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 2


def test_si_falla_a_media_escritura_se_queda_lo_de_antes(tmp_path):
    """La tabla se reemplaza entera o no se toca: nunca a medias.

    Se provoca el fallo con dos claves distintas que acaban en la misma fila:
    `variante=None` se guarda como -1, así que colisiona con una variante -1
    literal y salta la clave primaria a mitad del executemany.
    """
    con = abrir(tmp_path / "p.db")
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1305: resumen(100)}}, generado_en=1)

    with pytest.raises(sqlite3.IntegrityError):
        volcar(
            con,
            {
                Clave(TIPO_OBJETO, 2, None): {1305: resumen(200)},
                Clave(TIPO_OBJETO, 2, SIN_VARIANTE): {1305: resumen(300)},
            },
            generado_en=2,
        )

    # Sigue estando lo de la primera pasada, no una tabla vacía ni una mezcla.
    filas = con.execute("SELECT producto_id, minimo FROM precio").fetchall()
    assert [tuple(f) for f in filas] == [(1, 100)]
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 1


def test_estadisticas_de_un_producto(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_OBJETO, 271440, 305): {
            1305: resumen(400_000_000),
            1329: resumen(600_000_000),
            3391: resumen(900_000_000),
        }
    }
    volcar(con, agregado, generado_en=1)
    recalcular_estadisticas(con)

    fila = con.execute("SELECT * FROM estadistica").fetchone()
    assert fila["minimo"] == 400_000_000
    assert fila["maximo"] == 900_000_000
    assert fila["mediana"] == 600_000_000
    assert fila["reinos"] == 3


def test_con_un_numero_par_de_reinos_la_mediana_es_la_de_arriba(tmp_path):
    """No se interpola: la mediana tiene que ser un precio que exista.

    Un promedio entre dos reinos daría un número que no se cumple en ninguno,
    y este número se le enseña al usuario como "lo que cuesta normalmente".
    """
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_OBJETO, 1, 305): {
            1: resumen(100),
            2: resumen(200),
            3: resumen(300),
            4: resumen(400),
        }
    }
    volcar(con, agregado, generado_en=1)
    recalcular_estadisticas(con)
    assert con.execute("SELECT mediana FROM estadistica").fetchone()[0] == 300


def test_un_solo_reino_es_su_propia_mediana(tmp_path):
    con = abrir(tmp_path / "p.db")
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1: resumen(700)}}, generado_en=1)
    recalcular_estadisticas(con)

    fila = con.execute("SELECT * FROM estadistica").fetchone()
    assert (fila["mediana"], fila["minimo"], fila["maximo"], fila["reinos"]) == (
        700, 700, 700, 1
    )


def test_cada_variante_lleva_su_propia_estadistica(tmp_path):
    """El mismo objeto a ilvl 295 y a 318 son dos mercados distintos."""
    con = abrir(tmp_path / "p.db")
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 1, 295): {1: resumen(100), 2: resumen(200)},
            Clave(TIPO_OBJETO, 1, 318): {1: resumen(9000), 2: resumen(11000)},
        },
        generado_en=1,
    )
    recalcular_estadisticas(con)

    filas = {
        f["variante"]: f["mediana"]
        for f in con.execute("SELECT variante, mediana FROM estadistica")
    }
    assert filas == {295: 200, 318: 11000}


def test_sin_precios_no_hay_estadisticas(tmp_path):
    """Una base recién creada, antes de la primera pasada."""
    con = abrir(tmp_path / "p.db")
    assert recalcular_estadisticas(con) == 0
    assert con.execute("SELECT count(*) FROM estadistica").fetchone()[0] == 0


def test_recalcular_reemplaza_lo_anterior(tmp_path):
    con = abrir(tmp_path / "p.db")
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1: resumen(100)}}, generado_en=1)
    recalcular_estadisticas(con)
    volcar(con, {Clave(TIPO_OBJETO, 2, 305): {1: resumen(200)}}, generado_en=2)
    recalcular_estadisticas(con)

    filas = con.execute("SELECT producto_id FROM estadistica").fetchall()
    assert [f[0] for f in filas] == [2]


def test_guardar_reinos(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_reinos(con, {1305: "Kazzak", 1379: "Zul'jin / Uldum"})

    fila = con.execute("SELECT * FROM reino WHERE id = 1379").fetchone()
    assert fila["nombre"] == "Zul'jin / Uldum"
    assert fila["slug"] == "zuljin-uldum"


def test_guardar_reinos_actualiza_los_que_ya_estaban(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_reinos(con, {1305: "Kazzak"})
    guardar_reinos(con, {1305: "Kazzak Renombrado"})

    filas = con.execute("SELECT nombre FROM reino").fetchall()
    assert [f[0] for f in filas] == ["Kazzak Renombrado"]


def test_los_reinos_cirilicos_tienen_slug_propio(tmp_path):
    """Quitar los acentos deja en nada un nombre en cirílico.

    Son reinos de verdad de EU. Sin esto los tres compartirían el slug vacío y
    /realm/ devolvería cualquiera de ellos.
    """
    con = abrir(tmp_path / "p.db")
    guardar_reinos(
        con,
        {1602: "Гордунни", 1604: "Свежеватель Душ", 1615: "Ревущий фьорд"},
    )

    slugs = [f[0] for f in con.execute("SELECT slug FROM reino ORDER BY id")]
    assert all(s for s in slugs), f"algún slug vino vacío: {slugs}"
    assert len(set(slugs)) == 3, f"slugs repetidos: {slugs}"


def test_slug_de_un_nombre_normal():
    assert slug("Blackmoore / Tichondrius / Lordaeron") == "blackmoore-tichondrius-lordaeron"
    assert slug("Dentarg / Tarren Mill") == "dentarg-tarren-mill"


def test_guardar_nombres(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", "http://i/1.jpg"),
            (TIPO_OBJETO, 271440, "es", "Grebas de las profundidades nocivas", None),
        ],
    )
    fila = con.execute(
        "SELECT * FROM nombre WHERE producto_id = 271440 AND idioma = 'es'"
    ).fetchone()
    assert fila["nombre"] == "Grebas de las profundidades nocivas"
    assert fila["icono"] is None


def test_guardar_nombres_actualiza_los_que_ya_estaban(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "Viejo", None)])
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "Nuevo", "http://i/2.jpg")])

    filas = con.execute("SELECT nombre, icono FROM nombre").fetchall()
    assert [tuple(f) for f in filas] == [("Nuevo", "http://i/2.jpg")]
