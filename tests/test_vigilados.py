"""El fichero que le dice al addon que objetos repostear."""

from __future__ import annotations

from pathlib import Path

import pytest

import generar_vigilados
from generar_vigilados import a_lua, duracion_de, objetos_a_repostear
from wowalerts.blizzard import BlizzardAuthError
from wowalerts.config import ConfigError, ItemRule, load_config

RAIZ = Path(__file__).resolve().parent.parent
GENERADO = RAIZ / "addon" / "WowAlertsExport" / "Vigilados.lua"

CONFIG_MINIMO = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Otro"
    max_price: 100
"""

CONFIG_REPOSTEO_SIN_UNDERCUT = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Receta"
    max_price: 100
    avisar_undercut: false
    repostear: true
"""


def test_la_duracion_sale_de_listing_hours():
    assert duracion_de(12) == 1
    assert duracion_de(24) == 2
    assert duracion_de(48) == 3


def test_una_duracion_que_el_juego_no_admite_se_explica():
    with pytest.raises(ConfigError, match="12, 24 o 48"):
        duracion_de(6)


def test_entran_los_objetos_marcados_para_repostear():
    reglas = {
        1: ItemRule(name="Grebas", max_price=10),
        2: ItemRule(name="Patron", max_price=10, avisar_undercut=False),
        3: ItemRule(
            name="Receta", max_price=10, avisar_undercut=False, repostear=True
        ),
        4: ItemRule(name="Montura", max_price=10, repostear=False),
    }
    assert objetos_a_repostear(reglas) == {1: "Grebas", 3: "Receta"}


def test_las_mascotas_no_entran_en_objetos_a_repostear():
    reglas = {
        1: ItemRule(name="Grebas", max_price=10),
        2: ItemRule(name="Mascota", max_price=10, pet_species_id=123),
    }
    assert objetos_a_repostear(reglas) == {1: "Grebas"}


def test_el_lua_generado_se_carga_y_escapa_las_comillas():
    lupa = pytest.importorskip("lupa")
    nombre = 'Grebas "raras"\ncon barra\\y salto'
    texto = a_lua({271440: nombre}, ["Pepe"], 1)

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    vigilados = lua.globals().WowAlertsVigilados
    assert vigilados.objetos[271440] == nombre
    assert vigilados.personajes[1] == "Pepe"
    assert vigilados.duracion == 1


def test_el_fichero_del_repositorio_esta_al_dia_con_config_yaml():
    """Si cambias config.yaml y no regeneras, el addon repostea otra cosa.

    Arreglo: .venv\\Scripts\\python.exe generar_vigilados.py
    """
    lupa = pytest.importorskip("lupa")
    config = load_config(RAIZ / "config.yaml")
    texto = GENERADO.read_text(encoding="utf-8")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    vigilados = lua.globals().WowAlertsVigilados

    esperados = {r.name for r in config.items if r.se_repostea and not r.es_mascota}
    assert set(vigilados.objetos.values()) == esperados
    assert list(vigilados.personajes.values()) == list(config.orden_personajes)
    assert vigilados.duracion == duracion_de(config.settings.listing_hours)


def test_credenciales_invalidas_no_rompen_con_traceback(tmp_path, monkeypatch):
    """Un fallo de credenciales debe parar limpio, no reventar con traceback."""
    monkeypatch.setattr(generar_vigilados, "load_dotenv", lambda *a, **k: None)

    def _falla(client, config, cache):
        raise BlizzardAuthError("credenciales invalidas")

    monkeypatch.setattr(generar_vigilados, "resolve_item_ids", _falla)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_MINIMO, encoding="utf-8")
    salida = tmp_path / "Vigilados.lua"

    codigo = generar_vigilados.main(
        [
            "--config", str(config_path),
            "--state-dir", str(tmp_path / "estado"),
            "--salida", str(salida),
        ]
    )

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()


def test_falta_un_repostear_sin_undercut_no_escribe_nada_y_avisa(tmp_path, monkeypatch):
    """Un objeto con `repostear: true` y `avisar_undercut: false` sin id
    resuelto debe avisar igual: no lleva undercut, pero si tiene que repostearse.
    """
    monkeypatch.setattr(generar_vigilados, "load_dotenv", lambda *a, **k: None)

    def _resuelve_a_medias(client, config, cache):
        # Falta "Receta": simula que no se ha podido identificar su id.
        return {1: ItemRule(name="Grebas", max_price=100)}

    monkeypatch.setattr(generar_vigilados, "resolve_item_ids", _resuelve_a_medias)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_REPOSTEO_SIN_UNDERCUT, encoding="utf-8")
    salida = tmp_path / "Vigilados.lua"

    codigo = generar_vigilados.main(
        [
            "--config", str(config_path),
            "--state-dir", str(tmp_path / "estado"),
            "--salida", str(salida),
        ]
    )

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()


def test_un_objeto_no_resuelto_no_escribe_nada_y_avisa(tmp_path, monkeypatch):
    """Si falta el id de un objeto, el script no debe escribir un fichero incompleto."""
    monkeypatch.setattr(generar_vigilados, "load_dotenv", lambda *a, **k: None)

    def _resuelve_a_medias(client, config, cache):
        # Falta "Otro": simula que no se ha podido identificar su id.
        return {1: ItemRule(name="Grebas", max_price=100)}

    monkeypatch.setattr(generar_vigilados, "resolve_item_ids", _resuelve_a_medias)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_MINIMO, encoding="utf-8")
    salida = tmp_path / "Vigilados.lua"

    codigo = generar_vigilados.main(
        [
            "--config", str(config_path),
            "--state-dir", str(tmp_path / "estado"),
            "--salida", str(salida),
        ]
    )

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()
