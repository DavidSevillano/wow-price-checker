import pytest

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.db import abrir
from web.consultas import REINOS_GRATIS, anotar_peticion, ficha, paginas_mas_pedidas, reinos_de
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


def test_sin_volcado_la_ficha_sale_sin_fecha_en_vez_de_reventar(con):
    """Una base a medias no debe tumbar la página, solo dejarla sin fecha.

    No pasa por el camino normal --`volcar` escribe precio y volcado en la
    misma transacción-- pero sí con una base restaurada a medias o con un
    borrado a mano, y ahí un 500 es peor que una ficha sin sello de hora.
    """
    con.execute("DELETE FROM volcado")

    f = ficha(con, TIPO_OBJETO, 271440)
    assert f is not None
    assert f["nombre"] == "Greaves of the Noxious Depths"
    assert f["generado_en"] is None


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


def test_la_primera_peticion_crea_la_pagina(con):
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=1000)

    fila = con.execute("SELECT * FROM pagina").fetchone()
    assert fila["producto_id"] == 271440
    assert fila["primera_peticion"] == 1000
    assert fila["peticiones"] == 1


def test_las_siguientes_solo_cuentan(con):
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=1000)
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=2000)

    fila = con.execute("SELECT * FROM pagina").fetchone()
    assert fila["peticiones"] == 2
    # La fecha es la de la PRIMERA vez: dice desde cuándo existe la página.
    assert fila["primera_peticion"] == 1000


def test_sin_hora_usa_la_de_ahora(con):
    import time

    antes = int(time.time())
    anotar_peticion(con, TIPO_OBJETO, 271440)
    fila = con.execute("SELECT primera_peticion FROM pagina").fetchone()
    assert antes <= fila[0] <= int(time.time())


def test_las_mas_pedidas_salen_primero(con):
    anotar_peticion(con, TIPO_OBJETO, 1, ahora=1)
    for _ in range(3):
        anotar_peticion(con, TIPO_OBJETO, 2, ahora=1)

    assert [p["producto_id"] for p in paginas_mas_pedidas(con, limite=2)] == [2, 1]


def test_sin_paginas_pedidas_la_lista_esta_vacia(con):
    """Un sitio recién desplegado: el sitemap sale vacío, no con 20.144 URLs."""
    assert paginas_mas_pedidas(con, limite=100) == []


def test_un_fallo_al_contar_no_tumba_la_pagina(con, caplog):
    """Contar visitas es contabilidad, no contenido.

    Se tira la tabla para provocar un fallo de verdad de SQLite, en vez de
    simularlo: si `anotar_peticion` dejara subir la excepción, el visitante
    se llevaría un 500 con la ficha ya cargada y lista para pintarse.
    """
    import logging as _logging

    con.execute("DROP TABLE pagina")

    with caplog.at_level(_logging.WARNING):
        anotar_peticion(con, TIPO_OBJETO, 271440)  # no debe lanzar

    assert "271440" in caplog.text


def test_hay_que_decir_cuantas_paginas_se_quieren(con):
    """Sin valor por defecto: un sitemap truncado en silencio no se ve."""
    with pytest.raises(TypeError):
        paginas_mas_pedidas(con)
