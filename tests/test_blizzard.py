import pytest
import requests

from wowalerts.blizzard import (
    TOKEN_URL,
    BlizzardAuthError,
    BlizzardClient,
    BlizzardError,
    _realm_id_from_href,
)

AUCTIONS_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/1305/auctions"
INDEX_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/index"
SEARCH_URL = "https://eu.api.blizzard.com/data/wow/search/item"
REALM_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/1305"


@pytest.fixture
def client():
    return BlizzardClient(
        "id", "secret", session=requests.Session(), sleep=lambda _: None
    )


def give_token(requests_mock):
    requests_mock.post(TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})


def test_sin_credenciales_avisa_de_que_faltan():
    client = BlizzardClient("", "", session=requests.Session())
    with pytest.raises(BlizzardAuthError, match="BLIZZARD_CLIENT_ID"):
        _ = client.token


def test_credenciales_rechazadas(requests_mock, client):
    requests_mock.post(TOKEN_URL, status_code=401)
    with pytest.raises(BlizzardAuthError, match="rechaza las credenciales"):
        _ = client.token


def test_el_token_se_pide_una_sola_vez(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, json={"auctions": []})

    client.auctions(1305)
    client.auctions(1305)

    token_calls = [r for r in requests_mock.request_history if r.url.startswith(TOKEN_URL)]
    assert len(token_calls) == 1


def test_las_peticiones_van_firmadas(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, json={"auctions": []})

    client.auctions(1305)

    assert requests_mock.last_request.headers["Authorization"] == "Bearer tok"


def test_reintenta_ante_un_error_temporal(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        [{"status_code": 503}, {"status_code": 200, "json": {"auctions": [{"id": 1}]}}],
    )

    assert client.auctions(1305).auctions == [{"id": 1}]


def test_lee_la_hora_del_volcado_de_la_cabecera(requests_mock, client):
    """Last-Modified trae la hora del volcado, no la de la respuesta."""
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        json={"auctions": []},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    taken_at = client.auctions(1305).taken_at

    assert taken_at is not None
    assert taken_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-08-30 11:31:16"


@pytest.mark.parametrize("cabecera", [None, "", "esto no es una fecha"])
def test_una_cabecera_de_fecha_ausente_o_rara_no_rompe(requests_mock, client, cabecera):
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        json={"auctions": []},
        headers={"Last-Modified": cabecera} if cabecera is not None else {},
    )

    assert client.auctions(1305).taken_at is None


def test_respeta_el_retry_after_de_blizzard(requests_mock):
    esperas = []
    client = BlizzardClient("id", "secret", session=requests.Session(), sleep=esperas.append)
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        [
            {"status_code": 429, "headers": {"Retry-After": "3"}},
            {"status_code": 200, "json": {"auctions": []}},
        ],
    )

    client.auctions(1305)

    assert esperas == [3.0]


def test_un_reino_que_falla_siempre_lanza_error(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, status_code=500)

    with pytest.raises(BlizzardError, match="1305"):
        client.auctions(1305)


def test_lista_de_reinos_conectados(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        INDEX_URL,
        json={
            "connected_realms": [
                {"href": "https://eu.api.blizzard.com/data/wow/connected-realm/1305?namespace=dynamic-eu"},
                {"href": "https://eu.api.blizzard.com/data/wow/connected-realm/509?namespace=dynamic-eu"},
                {"href": "esto no vale"},
            ]
        },
    )

    assert client.connected_realm_ids() == [509, 1305]


def test_nombre_del_reino(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL, json={"realms": [{"name": "Dun Modr"}, {"name": "Sanguino"}]}
    )

    assert client.connected_realm_name(1305) == "Dun Modr / Sanguino"


def test_un_reino_ruso_se_muestra_en_cirilico(requests_mock, client):
    """Asi es como aparece en el juego a quien juega ahi."""
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={
            "realms": [
                {
                    "locale": "ruRU",
                    "name": {"en_GB": "Howling Fjord", "ru_RU": "Ревущий фьорд"},
                }
            ]
        },
    )

    assert client.connected_realm_name(1305) == "Ревущий фьорд"


def test_varios_reinos_rusos_agrupados(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={
            "realms": [
                {"locale": "ruRU", "name": {"en_GB": "Goldrinn", "ru_RU": "Голдринн"}},
                {"locale": "ruRU", "name": {"en_GB": "Greymane", "ru_RU": "Седогрив"}},
            ]
        },
    )

    assert client.connected_realm_name(1305) == "Голдринн / Седогрив"


def test_un_reino_no_ruso_conserva_su_nombre(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={"realms": [{"locale": "enGB", "name": {"en_GB": "Kazzak", "ru_RU": "Каззак"}}]},
    )

    assert client.connected_realm_name(1305) == "Kazzak"


def test_sin_el_idioma_propio_cae_al_del_cliente(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={"realms": [{"locale": "xxYY", "name": {"en_GB": "Silvermoon"}}]},
    )

    assert client.connected_realm_name(1305) == "Silvermoon"


def test_el_nombre_del_reino_se_pide_sin_locale(requests_mock, client):
    """Con locale, Blizzard devuelve un solo idioma y no se puede elegir."""
    give_token(requests_mock)
    requests_mock.get(REALM_URL, json={"realms": []})

    client.connected_realm_name(1305)

    assert "locale" not in requests_mock.last_request.qs


def test_nombre_del_reino_cae_al_id_si_falla(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(REALM_URL, status_code=404)

    assert client.connected_realm_name(1305) == "Reino 1305"


def test_busqueda_exige_coincidencia_exacta_de_nombre(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        SEARCH_URL,
        json={
            "results": [
                {"data": {"id": 1, "name": {"en_GB": "Slitherscale Girdle of Doom"}}},
                {"data": {"id": 2, "name": {"en_GB": "Slitherscale Girdle"}}},
            ]
        },
    )

    assert client.search_item_id("Slitherscale Girdle") == 2


def test_busqueda_sin_coincidencia_devuelve_none(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(SEARCH_URL, json={"results": []})

    assert client.search_item_id("Objeto Inventado") is None


@pytest.mark.parametrize(
    "href,esperado",
    [
        ("https://eu.api.blizzard.com/data/wow/connected-realm/1305?namespace=dynamic-eu", 1305),
        ("https://eu.api.blizzard.com/data/wow/connected-realm/509", 509),
        ("https://eu.api.blizzard.com/data/wow/realm/509", None),
        ("", None),
    ],
)
def test_extraccion_del_id_de_reino(href, esperado):
    assert _realm_id_from_href(href) == esperado
