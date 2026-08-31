"""Sincronizacion del volcado del addon al repositorio."""

import json
import re
from dataclasses import replace

from sync_subastas import detectar_wow_root, nombre_de_maquina
from wowalerts.misubastas import (
    MyAuction,
    escribir_snapshot,
    leer_snapshot,
    leer_snapshots,
)


def una(auction_id=1, character="Pepe"):
    return MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name="Greaves of the Noxious Depths",
        ilvl=311,
        buyout_copper=90_000_000,
        quantity=1,
        character=character,
        realm="Sanguino",
        realm_slug="sanguino",
        bonus_ids=(12817, 6652),
    )


def test_el_primer_volcado_cuenta_como_cambio(tmp_path):
    assert escribir_snapshot(tmp_path / "mis.json", [una()]) is True


def test_el_mismo_contenido_no_cuenta_como_cambio(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert escribir_snapshot(path, [una()]) is False


def test_un_precio_distinto_si_cuenta_como_cambio(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert escribir_snapshot(path, [replace(una(), buyout_copper=80_000_000)]) is True


def test_el_snapshot_no_lleva_marcas_de_tiempo(tmp_path):
    """Sin esto, la tarea programada generaria un commit cada cuarto de hora
    aunque no hubieras tocado nada."""
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert "exportedAt" not in path.read_text(encoding="utf-8")


def test_lo_escrito_se_puede_volver_a_leer(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert leer_snapshot(path) == [una()]


def test_leer_un_snapshot_que_no_existe_son_cero_subastas(tmp_path):
    assert leer_snapshot(tmp_path / "no-existe.json") == []


def test_el_snapshot_es_json_valido(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una(), una(auction_id=2, character="Ana")])
    datos = json.loads(path.read_text(encoding="utf-8"))
    assert len(datos["auctions"]) == 2


def test_detecta_la_carpeta_de_wow(tmp_path):
    raiz = tmp_path / "World of Warcraft" / "_retail_"
    (raiz / "WTF").mkdir(parents=True)
    assert detectar_wow_root([str(raiz)]) == raiz


def test_sin_carpeta_de_wow_devuelve_none(tmp_path):
    assert detectar_wow_root([str(tmp_path / "no-existe")]) is None


# -- Varias maquinas --------------------------------------------------------


def test_une_las_subastas_de_dos_maquinas(tmp_path):
    """El PC y la Steam Deck escriben cada uno su fichero: si compartieran uno,
    cada maquina borraria al subir los personajes del otro."""
    escribir_snapshot(tmp_path / "pc.json", [una(1, "Pepe")])
    escribir_snapshot(tmp_path / "deck.json", [una(2, "Ana")])

    assert {s.character for s in leer_snapshots(tmp_path)} == {"Pepe", "Ana"}


def test_una_subasta_en_las_dos_maquinas_se_cuenta_una_vez(tmp_path):
    escribir_snapshot(tmp_path / "pc.json", [una(1), una(2)])
    escribir_snapshot(tmp_path / "deck.json", [una(2), una(3)])

    assert [s.auction_id for s in leer_snapshots(tmp_path)] == [1, 2, 3]


def test_tambien_lee_un_fichero_suelto(tmp_path):
    """Como estaba antes de haber dos maquinas."""
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert len(leer_snapshots(path)) == 1


def test_una_carpeta_que_no_existe_son_cero_subastas(tmp_path):
    assert leer_snapshots(tmp_path / "no-existe") == []


def test_el_nombre_de_maquina_vale_como_nombre_de_fichero():
    nombre = nombre_de_maquina()
    assert nombre
    assert re.fullmatch(r"[a-z0-9_-]+", nombre), nombre
