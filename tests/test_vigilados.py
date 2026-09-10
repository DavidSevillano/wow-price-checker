"""El fichero que le dice al addon que objetos repostear."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from generar_vigilados import a_lua, duracion_de, objetos_a_repostear
from wowalerts.config import ConfigError, ItemRule, load_config

RAIZ = Path(__file__).resolve().parent.parent
GENERADO = RAIZ / "addon" / "WowAlertsExport" / "Vigilados.lua"


def test_la_duracion_sale_de_listing_hours():
    assert duracion_de(12) == 1
    assert duracion_de(24) == 2
    assert duracion_de(48) == 3


def test_una_duracion_que_el_juego_no_admite_se_explica():
    with pytest.raises(ConfigError, match="12, 24 o 48"):
        duracion_de(6)


def test_solo_entran_los_objetos_con_avisos_de_undercut():
    reglas = {
        1: ItemRule(name="Grebas", max_price=10),
        2: ItemRule(name="Patron", max_price=10, avisar_undercut=False),
    }
    assert objetos_a_repostear(reglas) == {1: "Grebas"}


def test_el_lua_generado_se_carga_y_escapa_las_comillas():
    lupa = pytest.importorskip("lupa")
    texto = a_lua({271440: 'Grebas "raras"'}, ["Pepe"], 1)

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    vigilados = lua.globals().WowAlertsVigilados
    assert vigilados.objetos[271440] == 'Grebas "raras"'
    assert vigilados.personajes[1] == "Pepe"
    assert vigilados.duracion == 1


def test_el_fichero_del_repositorio_esta_al_dia_con_config_yaml():
    """Si cambias config.yaml y no regeneras, el addon repostea otra cosa.

    Arreglo: .venv\\Scripts\\python.exe generar_vigilados.py
    """
    config = load_config(RAIZ / "config.yaml")
    texto = GENERADO.read_text(encoding="utf-8")

    nombres = set(re.findall(r'^\s+\[\d+\] = "(.*)",$', texto, re.MULTILINE))
    esperados = {
        r.name for r in config.items if r.avisar_undercut and not r.es_mascota
    }
    assert nombres == esperados

    bloque = texto.split("personajes = {", 1)[1].split("}", 1)[0]
    personajes = re.findall(r'"(.*)",', bloque)
    assert personajes == list(config.orden_personajes)

    assert f"duracion = {duracion_de(config.settings.listing_hours)}," in texto
