"""Pruebas de punta a punta: del config.yaml al mensaje de Discord.

Toda la red esta simulada, asi que no se toca la API de Blizzard ni se envia
nada a Discord de verdad.
"""

import json
import logging
from datetime import datetime, timezone

import pytest

import main as cli

WEBHOOK = "https://discord.com/api/webhooks/1/abc"
TOKEN_URL = "https://oauth.battle.net/token"
BASE = "https://eu.api.blizzard.com/data/wow"
ICON_URL = "https://render.worldofwarcraft.com/eu/icons/56/7705643.jpg"

CONFIG = """
region: eu
items:
  - name: "Greaves of the Noxious Depths"
    item_id: 5000
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
bonus_ilvl_map:
  12843: 311
settings:
  max_workers: 2
"""


def subasta(auction_id, buyout, bonus=(12843,)):
    return {
        "id": auction_id,
        "item": {"id": 5000, "bonus_lists": list(bonus)},
        "buyout": buyout,
        "quantity": 1,
        "time_left": "LONG",
    }


@pytest.fixture
def entorno(tmp_path, monkeypatch, requests_mock):
    # Sin esto, los reintentos con espera progresiva harian los tests lentisimos.
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "id")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "secret")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")

    requests_mock.post(TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})
    requests_mock.get(
        f"{BASE}/connected-realm/index",
        json={"connected_realms": [{"href": f"{BASE}/connected-realm/1305"}]},
    )
    requests_mock.get(
        f"{BASE}/connected-realm/1305", json={"realms": [{"name": "Dun Modr"}]}
    )
    requests_mock.get(
        f"{BASE}/media/item/5000",
        json={"assets": [{"key": "icon", "value": ICON_URL}]},
    )
    requests_mock.post(WEBHOOK, status_code=204)

    return {
        "config": str(config_path),
        "state": str(tmp_path / "estado"),
        "mock": requests_mock,
    }


def ejecutar(entorno, *extra):
    return cli.main(
        ["--config", entorno["config"], "--state-dir", entorno["state"], *extra]
    )


def mensajes_discord(requests_mock):
    return [r.json() for r in requests_mock.request_history if r.url == WEBHOOK]


def test_una_pasada_completa_avisa_del_chollo(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK

    enviados = mensajes_discord(entorno["mock"])
    assert len(enviados) == 1
    embed = enviados[0]["embeds"][0]
    assert embed["title"] == "Greaves of the Noxious Depths"
    assert "45.000" in embed["description"]
    assert any(f["value"] == "Dun Modr" for f in embed["fields"])


def test_el_aviso_lleva_miniatura_y_hora_del_volcado(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    ejecutar(entorno)

    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert embed["thumbnail"] == {"url": ICON_URL}
    assert embed["timestamp"].startswith("2026-08-30T11:31:16")


def test_el_icono_se_cachea_entre_pasadas(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000), subasta(2, 44_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno, "--ignore-state")

    peticiones = [r for r in entorno["mock"].request_history if "/media/item/" in r.url]
    assert len(peticiones) == 1


def test_un_fallo_al_pedir_el_icono_no_impide_el_aviso(entorno):
    entorno["mock"].get(f"{BASE}/media/item/5000", status_code=404)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK

    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert "thumbnail" not in embed
    assert embed["title"] == "Greaves of the Noxious Depths"


def test_ningun_chollo_se_pierde_cuando_hay_mas_de_los_que_caben(entorno):
    """Lo que no cabe en un aviso se envia en la pasada siguiente.

    El fallo que esto evita: marcar como avisados los que no se enviaron, con
    lo que desaparecerian para siempre.
    """
    from wowalerts.notifier import MAX_DEALS_PER_RUN

    total = MAX_DEALS_PER_RUN + 7
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(i, (30_000 + i) * 10_000) for i in range(total)]},
    )

    ejecutar(entorno)
    primera = sum(len(m["embeds"]) for m in mensajes_discord(entorno["mock"]))
    assert primera == MAX_DEALS_PER_RUN

    ejecutar(entorno)
    total_enviado = sum(len(m["embeds"]) for m in mensajes_discord(entorno["mock"]))
    assert total_enviado == total, "los 7 sobrantes tienen que llegar en la 2a pasada"


def test_la_segunda_pasada_no_repite_el_mismo_chollo(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno)

    assert len(mensajes_discord(entorno["mock"])) == 1


def test_ignore_state_vuelve_a_avisar(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno, "--ignore-state")

    assert len(mensajes_discord(entorno["mock"])) == 2


def test_sin_chollos_no_se_envia_nada(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 200_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK
    assert mensajes_discord(entorno["mock"]) == []


def test_una_subasta_solo_con_puja_no_dispara_alerta(entorno):
    """El fallo clasico: sin buyout, el precio 0 pasaba cualquier filtro."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [{"id": 1, "item": {"id": 5000, "bonus_lists": [12843]}, "bid": 100}]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK
    assert mensajes_discord(entorno["mock"]) == []


def test_dry_run_no_envia_ni_guarda_estado(entorno, tmp_path):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno, "--dry-run") == cli.EXIT_OK

    assert mensajes_discord(entorno["mock"]) == []
    assert not (tmp_path / "estado" / "notified.json").exists()


def test_realms_limita_el_escaneo(entorno):
    """Con --realms no se pide el indice de reinos de toda la region."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions", json={"auctions": []}
    )

    assert ejecutar(entorno, "--realms", "1305") == cli.EXIT_OK

    urls = [r.url for r in entorno["mock"].request_history]
    assert not any("connected-realm/index" in u for u in urls)


def test_realms_mal_escrito_da_error_claro(entorno, caplog):
    assert ejecutar(entorno, "--realms", "1305,silvermoon") == cli.EXIT_CONFIG_ERROR
    assert "--realms" in caplog.text


def test_test_discord_envia_solo_el_mensaje_de_prueba(entorno):
    assert ejecutar(entorno, "--test-discord") == cli.EXIT_OK

    enviados = mensajes_discord(entorno["mock"])
    assert len(enviados) == 1
    assert "Prueba de conexion" in enviados[0]["content"]


def test_demasiados_reinos_caidos_termina_con_error(entorno):
    entorno["mock"].get(f"{BASE}/connected-realm/1305/auctions", status_code=500)

    assert ejecutar(entorno) == cli.EXIT_TOO_MANY_FAILURES

    avisos = mensajes_discord(entorno["mock"])
    assert "Escaneo incompleto" in avisos[0]["embeds"][0]["title"]


def test_credenciales_invalidas_dan_error_de_configuracion(entorno, caplog):
    entorno["mock"].post(TOKEN_URL, status_code=401)

    assert ejecutar(entorno) == cli.EXIT_CONFIG_ERROR
    assert "BLIZZARD_CLIENT_ID" in caplog.text


def test_config_inexistente(tmp_path, caplog):
    assert cli.main(["--config", str(tmp_path / "no.yaml")]) == cli.EXIT_CONFIG_ERROR
    assert "No encuentro el fichero" in caplog.text


def test_informa_de_la_antiguedad_del_volcado(entorno, caplog):
    caplog.set_level(logging.INFO)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    ejecutar(entorno)

    assert "11:31 UTC" in caplog.text


def test_el_estado_guardado_es_legible(entorno, tmp_path):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)

    estado = json.loads((tmp_path / "estado" / "notified.json").read_text(encoding="utf-8"))
    assert estado["auctions"] == {"1305:1": 1}


# ---------------------------------------------------------------------------
#  Reintento cuando Blizzard publica el volcado tarde
# ---------------------------------------------------------------------------
#
#  El cron dispara a y 33 porque el volcado sale a y 31. Si Blizzard se
#  retrasa, la pasada se encuentra los datos de la hora anterior y, sin
#  reintento, no habria otra oportunidad hasta la hora siguiente.

AHORA = datetime(2026, 8, 30, 12, 33, tzinfo=timezone.utc)
VOLCADO_VIEJO = {"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"}
VOLCADO_NUEVO = {"Last-Modified": "Sun, 30 Aug 2026 12:31:16 GMT"}


@pytest.fixture
def reloj_parado(monkeypatch):
    """Congela el reloj a y 33, que es cuando corre el cron de verdad."""

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return AHORA

    monkeypatch.setattr(cli, "datetime", Reloj)


@pytest.fixture
def esperas(monkeypatch):
    """Recoge las esperas en vez de dormirlas."""
    dormido = []
    monkeypatch.setattr("time.sleep", lambda s: dormido.append(s))
    return dormido


def escaneos(requests_mock):
    return [r for r in requests_mock.request_history if r.path.endswith("/auctions")]


def con_ajustes(entorno, tmp_path, extra):
    """Reescribe el config con opciones adicionales dentro de 'settings'."""
    path = tmp_path / "config-ajustado.yaml"
    path.write_text(CONFIG + extra, encoding="utf-8")
    entorno["config"] = str(path)
    return entorno


def test_si_el_volcado_va_tarde_se_espera_y_se_vuelve_a_mirar(
    entorno, reloj_parado, esperas
):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {"json": {"auctions": []}, "headers": VOLCADO_VIEJO},
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_NUEVO,
            },
        ],
    )

    assert ejecutar(entorno) == 0

    assert len(escaneos(entorno["mock"])) == 2
    assert esperas == [120]
    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert embed["title"] == "Greaves of the Noxious Depths"


def test_un_chollo_visto_solo_en_el_primer_intento_se_envia_igual(
    entorno, reloj_parado, esperas
):
    """La garantia que importa: reintentar no puede tragarse un aviso."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_VIEJO,
            },
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
        ],
    )

    ejecutar(entorno)

    # Hubo segundo intento y ya no traia el chollo: el aviso salio del primero.
    assert len(escaneos(entorno["mock"])) == 2
    embeds = [e for m in mensajes_discord(entorno["mock"]) for e in m["embeds"]]
    assert len(embeds) == 1
    assert embeds[0]["title"] == "Greaves of the Noxious Depths"


def test_no_se_avisa_dos_veces_del_mismo_chollo_entre_intentos(
    entorno, reloj_parado, esperas
):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_VIEJO,
            },
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_NUEVO,
            },
        ],
    )

    ejecutar(entorno)

    embeds = [e for m in mensajes_discord(entorno["mock"]) for e in m["embeds"]]
    assert len(embeds) == 1


def test_se_deja_de_reintentar_al_agotar_los_intentos(
    entorno, reloj_parado, esperas, caplog
):
    caplog.set_level(logging.WARNING)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_VIEJO,
    )

    assert ejecutar(entorno) == 0

    # El primer escaneo mas los dos reintentos que trae por defecto.
    assert len(escaneos(entorno["mock"])) == 3
    assert esperas == [120, 120]
    assert "ya no quedan" in caplog.text


def test_los_reintentos_se_pueden_desactivar(
    entorno, reloj_parado, esperas, tmp_path
):
    con_ajustes(entorno, tmp_path, "  stale_retries: 0\n")
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_VIEJO,
    )

    ejecutar(entorno)

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


def test_un_volcado_al_dia_no_provoca_ninguna_espera(entorno, reloj_parado, esperas):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_NUEVO,
    )

    ejecutar(entorno)

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


# -- Modo undercut ----------------------------------------------------------

from main import agrupar_por_reino, build_parser as _parser
from wowalerts.misubastas import MyAuction


def una_mia(auction_id=1, realm="Sanguino", slug="sanguino", item_id=200000):
    return MyAuction(
        auction_id=auction_id,
        item_id=item_id,
        item_name="Greaves of the Noxious Depths",
        ilvl=311,
        buyout_copper=90_000_000,
        quantity=1,
        character="Pepe",
        realm=realm,
        realm_slug=slug,
    )


def test_el_parser_acepta_undercut():
    assert _parser().parse_args(["--undercut"]).undercut is True


def test_agrupa_las_subastas_por_reino_conectado():
    mias = [
        una_mia(1, "Sanguino", "sanguino"),
        una_mia(2, "Dun Modr", "dun-modr"),
        una_mia(3, "Sanguino", "sanguino"),
    ]
    grupos = agrupar_por_reino(mias, {"Sanguino": 1379, "Dun Modr": 1379})
    # Los dos reinos comparten connected realm: una sola descarga.
    assert list(grupos) == [1379]
    assert len(grupos[1379]) == 3


def test_las_subastas_de_reinos_sin_resolver_se_omiten():
    mias = [una_mia(1, "Sanguino", "sanguino"), una_mia(2, "Fantasma", "fantasma")]
    grupos = agrupar_por_reino(mias, {"Sanguino": 1379})
    assert list(grupos) == [1379]
    assert len(grupos[1379]) == 1
