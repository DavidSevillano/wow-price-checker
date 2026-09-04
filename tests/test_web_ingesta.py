from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino
from web.db import abrir
from web.ingesta import SIN_VARIANTE, filas_de_precio, volcar


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
