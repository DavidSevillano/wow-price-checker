from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino
from web.consultas import ficha
from web.db import abrir
from web.ingesta import guardar_nombres

from publicar_web import poblar, productos_sin_nombre


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


def test_poblar_deja_precios_estadisticas_nombres_y_reinos(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_OBJETO, 271440, 305): {
            1305: resumen(500_000_000),
            1329: resumen(700_000_000),
        }
    }
    nombres_reino = {1305: "Kazzak", 1329: "Zul'jin / Uldum"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
        (TIPO_OBJETO, 271440, "es", "Grebas de las profundidades nocivas", None),
    ]

    filas = poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1788451184)

    assert filas == 2
    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM estadistica").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 2
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 1788451184


def test_poblar_dos_veces_no_duplica(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 1, 305): {1305: resumen(100)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [(TIPO_OBJETO, 1, "en", "Algo", None)]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)
    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=2)

    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 1
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 2


def test_solo_se_piden_los_nombres_que_faltan(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(con, [(TIPO_OBJETO, 111, "en", "Ya tengo nombre", None)])

    agregado = {
        Clave(TIPO_OBJETO, 111, 305): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 222, 305): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 222)]


def test_las_mascotas_no_piden_nombre(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_MASCOTA, 303, 3): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 111, None): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 111)]


def test_el_idioma_guardado_es_el_que_consulta_la_web(tmp_path):
    """Si el codigo de idioma no coincide con lo que consulta la web, la ficha
    cae al `#id` de repuesto en vez de ensenar el nombre de verdad -- esto es
    lo unico que demuestra que ingesta y web estan de acuerdo en el idioma.
    """
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
    ]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)

    resultado = ficha(con, TIPO_OBJETO, 271440)
    assert resultado["nombre"] == "Greaves of the Noxious Depths"
    assert resultado["nombre"] != "#271440"
