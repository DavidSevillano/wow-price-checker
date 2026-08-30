"""Pruebas de punta a punta: del config.yaml al mensaje de Discord.

Toda la red esta simulada, asi que no se toca la API de Blizzard ni se envia
nada a Discord de verdad.
"""

import json
import logging

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
