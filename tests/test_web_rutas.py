import pytest
from fastapi.testclient import TestClient

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.app import crear_app
from web.db import abrir
from web.ingesta import guardar_nombres, guardar_reinos, recalcular_estadisticas, volcar


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


@pytest.fixture
def ruta_db(tmp_path):
    ruta = tmp_path / "p.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        con, [(TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None)]
    )
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 271440, 305): {
                i: resumen(i * 1_000_000, listados=i) for i in range(1, 11)
            },
            Clave(TIPO_OBJETO, 271440, 318): {1: resumen(90_000_000)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente(ruta_db):
    return TestClient(crear_app(ruta_db))


def test_la_ficha_responde_con_el_nombre(cliente):
    r = cliente.get("/item/271440")
    assert r.status_code == 200
    assert "Greaves of the Noxious Depths" in r.text


def test_un_producto_desconocido_da_404(cliente):
    assert cliente.get("/item/999999").status_code == 404


def test_la_ficha_solo_pinta_cinco_reinos(cliente):
    texto = cliente.get("/item/271440").text
    assert "Reino 5" in texto
    # El sexto reino y los siguientes no llegan al HTML: el corte está en la
    # consulta, así que no hay nada que descubrir quitando una regla de CSS.
    assert "Reino 6" not in texto


def test_visitar_la_ficha_la_registra(cliente, ruta_db):
    cliente.get("/item/271440")
    con = abrir(ruta_db)
    assert con.execute("SELECT peticiones FROM pagina").fetchone()[0] == 1


def test_se_puede_pedir_una_variante_concreta(cliente):
    r = cliente.get("/item/271440?ilvl=318")
    assert r.status_code == 200
    assert "318" in r.text


def test_sin_ilvl_abre_por_la_variante_con_mas_mercado(cliente):
    """El 305 está en 10 reinos y el 318 en 1: se abre por el que enseña más."""
    texto = cliente.get("/item/271440").text
    assert "Reino 3" in texto


def test_un_ilvl_que_no_existe_no_revienta(cliente):
    """Una URL manipulada cae en la variante por defecto, no en un 500."""
    assert cliente.get("/item/271440?ilvl=9999").status_code == 200


def test_los_precios_salen_en_oro_y_no_en_cobre(cliente):
    """En la base todo es cobre; el usuario piensa en oro (10.000 cobre)."""
    texto = cliente.get("/item/271440").text
    assert "100" in texto            # 1.000.000 de cobre son 100 de oro
    assert "1000000" not in texto
