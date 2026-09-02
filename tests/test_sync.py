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


def test_el_snapshot_no_cambia_si_no_has_jugado(tmp_path):
    """Sin esto, la tarea programada generaria un commit cada cuarto de hora
    aunque no hubieras tocado nada.

    El volcado si lleva la hora a la que exporto el addon, que es lo que permite
    despues desconfiar de una maquina que se ha quedado atras. Pero esa hora la
    estampa el addon al recoger los datos de un personaje, no el sincronizador
    al escribir el fichero: si no juegas no cambia, y los bytes salen iguales.
    """
    path = tmp_path / "mis.json"
    assert escribir_snapshot(path, [una()]) is True
    primero = path.read_text(encoding="utf-8")

    assert escribir_snapshot(path, [una()]) is False
    assert path.read_text(encoding="utf-8") == primero


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


# -- Sin ventanas de consola en Windows -------------------------------------


def test_git_se_lanza_sin_abrir_ventana(monkeypatch):
    """La tarea corre con pythonw, que no tiene consola.

    Un proceso de consola lanzado desde ahi se abre la suya, y con cuatro
    llamadas a git por pasada eso son cuatro parpadeos cada quince minutos.
    """
    import subprocess as sp

    from sync_subastas import git

    visto = {}

    def falso(*args, **kwargs):
        visto.update(kwargs)
        return sp.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(sp, "run", falso)
    git("status")

    esperado = getattr(sp, "CREATE_NO_WINDOW", 0)
    assert visto.get("creationflags") == esperado


# ---------------------------------------------------------------------------
#  Vigilar la salida del juego
# ---------------------------------------------------------------------------
#
#  El addon solo vuelca al salir al selector o cerrar WoW. Si hubiera que
#  esperar al temporizador, lo normal seria apagar el equipo antes: lo exportado
#  se quedaria sin subir hasta el siguiente encendido, y para entonces las
#  subastas ya han caducado y no se puede saber si alguna se vendio.

import sync_subastas as sync


def con_volcado(tmp_path, cuenta="403840080#1", contenido="x"):
    ruta = tmp_path / "WTF" / "Account" / cuenta / "SavedVariables"
    ruta.mkdir(parents=True, exist_ok=True)
    fichero = ruta / "WowAlertsExport.lua"
    fichero.write_text(contenido, encoding="utf-8")
    return fichero


def test_la_firma_cambia_cuando_wow_guarda(tmp_path):
    con_volcado(tmp_path, contenido="antes")
    antes = sync.firma_de_los_volcados(tmp_path)

    con_volcado(tmp_path, contenido="despues, mas largo")

    assert sync.firma_de_los_volcados(tmp_path) != antes


def test_la_firma_no_cambia_sola(tmp_path):
    """Si cambiara sin motivo, se sincronizaria en bucle sin parar."""
    con_volcado(tmp_path)

    assert sync.firma_de_los_volcados(tmp_path) == sync.firma_de_los_volcados(tmp_path)


def test_la_firma_cubre_todas_las_cuentas(tmp_path):
    """Con varias cuentas de WoW hay un fichero por cada una."""
    con_volcado(tmp_path, cuenta="403840080#1")
    con_volcado(tmp_path, cuenta="403840080#3")

    assert len(sync.firma_de_los_volcados(tmp_path)) == 2


def test_una_carpeta_sin_volcados_da_firma_vacia(tmp_path):
    assert sync.firma_de_los_volcados(tmp_path) == ()
