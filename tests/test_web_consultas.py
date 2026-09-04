import pytest

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.db import abrir
from web.consultas import REINOS_GRATIS, ficha, reinos_de
from web.ingesta import guardar_nombres, guardar_reinos, recalcular_estadisticas, volcar


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


@pytest.fixture
def con(tmp_path):
    c = abrir(tmp_path / "p.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        c, [(TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", "http://i.jpg")]
    )
    agregado = {
        # 10 reinos, de 100 a 1000, para que se vea el corte de los 5 gratis.
        Clave(TIPO_OBJETO, 271440, 305): {i: resumen(i * 100, listados=i) for i in range(1, 11)},
        Clave(TIPO_OBJETO, 271440, 318): {1: resumen(9000)},
    }
    volcar(c, agregado, generado_en=1788451184)
    recalcular_estadisticas(c)
    return c


def test_la_ficha_trae_el_nombre_y_las_variantes(con):
    f = ficha(con, TIPO_OBJETO, 271440)
    assert f["nombre"] == "Greaves of the Noxious Depths"
    assert [v["variante"] for v in f["variantes"]] == [305, 318]


def test_la_ficha_trae_las_estadisticas_de_cada_variante(con):
    f = ficha(con, TIPO_OBJETO, 271440)
    v305 = f["variantes"][0]
    assert v305["minimo"] == 100
    assert v305["maximo"] == 1000
    assert v305["reinos"] == 10


def test_la_ficha_trae_cuando_se_generaron_los_datos(con):
    assert ficha(con, TIPO_OBJETO, 271440)["generado_en"] == 1788451184


def test_un_producto_que_no_existe_no_tiene_ficha(con):
    assert ficha(con, TIPO_OBJETO, 999999) is None


def test_un_producto_sin_nombre_traducido_sale_por_su_id(con):
    """Nunca una ficha en blanco: si falta el nombre, al menos el id."""
    volcar(con, {Clave(TIPO_OBJETO, 555, 305): {1: resumen(100)}}, generado_en=1)
    recalcular_estadisticas(con)

    f = ficha(con, TIPO_OBJETO, 555)
    assert f is not None
    assert "555" in f["nombre"]


def test_los_reinos_salen_de_mas_barato_a_mas_caro(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=None)
    assert [f["minimo"] for f in filas] == [i * 100 for i in range(1, 11)]
    assert filas[0]["nombre"] == "Reino 1"


def test_los_reinos_traen_cuantas_subastas_hay(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=None)
    assert filas[0]["listados"] == 1
    assert filas[9]["listados"] == 10


def test_el_plan_gratis_solo_ve_cinco_reinos(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=REINOS_GRATIS)
    assert len(filas) == REINOS_GRATIS
    # El muro está en la consulta, no en la plantilla: los otros cinco no
    # llegan a salir de la base, así que no hay nada que descubrir mirando el
    # HTML ni quitando una regla de CSS.
    assert [f["minimo"] for f in filas] == [100, 200, 300, 400, 500]


def test_lo_que_no_escala_se_pide_con_variante_none(con):
    """Un patrón o una montura no tienen ilvl; en la base son -1."""
    volcar(con, {Clave(TIPO_OBJETO, 258126, None): {1: resumen(4200)}}, generado_en=1)
    recalcular_estadisticas(con)

    filas = reinos_de(con, TIPO_OBJETO, 258126, None, limite=None)
    assert [f["minimo"] for f in filas] == [4200]
