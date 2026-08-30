import pytest
import requests

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.notifier import (
    COLOR_STEAL,
    COLOR_UNCONFIRMED,
    MAX_DEALS_PER_RUN,
    DiscordError,
    DiscordNotifier,
    build_embed,
    build_messages,
    format_gold,
    realm_names_for,
)
from wowalerts.scanner import Deal

WEBHOOK = "https://discord.com/api/webhooks/1/abc"
REALMS = {1305: "Dun Modr / Sanguino"}


def make_deal(auction_id=1, price_gold=45_000, threshold_gold=90_000, confirmed=True):
    return Deal(
        auction_id=auction_id,
        item_id=5000,
        item_name="Greaves of the Noxious Depths",
        ilvl=311 if confirmed else None,
        ilvl_confirmed=confirmed,
        price_copper=price_gold * COPPER_PER_GOLD,
        threshold_copper=threshold_gold * COPPER_PER_GOLD,
        realm_id=1305,
        time_left="LONG",
    )


def test_formato_de_oro_a_la_espanola():
    assert format_gold(1_234_567) == "1.234.567"
    assert format_gold(999) == "999"


def test_el_embed_lleva_precio_ilvl_reino_y_enlace():
    embed = build_embed(make_deal(), REALMS[1305])

    assert embed["title"] == "Greaves of the Noxious Depths"
    assert embed["url"].startswith("https://www.wowhead.com/item=5000")
    assert "45.000" in embed["description"]
    assert "ilvl **311**" in embed["description"]
    assert "50%" in embed["description"]
    assert embed["color"] == COLOR_STEAL
    assert {"name": "Reino", "value": "Dun Modr / Sanguino", "inline": True} in embed["fields"]
    assert any(f["name"] == "Tiempo restante" for f in embed["fields"])


def test_el_embed_avisa_cuando_el_ilvl_no_esta_confirmado():
    embed = build_embed(make_deal(confirmed=False), REALMS[1305])

    assert "sin confirmar" in embed["description"]
    assert "antes de comprar" in embed["description"]
    assert embed["color"] == COLOR_UNCONFIRMED


def test_cada_embed_del_mensaje_lleva_una_url_distinta():
    """Discord fusiona los embeds de un mensaje que comparten url.

    Varias subastas del mismo objeto tienen el mismo enlace de Wowhead, asi que
    sin un ancla unica se veian todas como un solo embed.
    """
    deals = [make_deal(auction_id=i) for i in range(10)]

    urls = [e["url"] for e in build_messages(deals, REALMS)[0]["embeds"]]

    assert len(set(urls)) == len(urls)
    assert all(u.startswith("https://www.wowhead.com/item=5000") for u in urls)


def test_sin_chollos_no_se_genera_ningun_mensaje():
    assert build_messages([], REALMS) == []


def test_un_solo_mensaje_con_cabecera_para_pocos_chollos():
    messages = build_messages([make_deal(1), make_deal(2)], REALMS)

    assert len(messages) == 1
    assert "2 chollos" in messages[0]["content"]
    assert len(messages[0]["embeds"]) == 2


def test_cabecera_en_singular_con_un_solo_chollo():
    messages = build_messages([make_deal()], REALMS)
    assert "1 chollo" in messages[0]["content"]
    assert "chollos" not in messages[0]["content"]


def test_se_reparte_en_mensajes_de_diez_embeds():
    messages = build_messages([make_deal(i) for i in range(25)], REALMS)

    assert [len(m["embeds"]) for m in messages] == [10, 10, 5]
    # Solo el primer mensaje lleva cabecera, para no repetirla.
    assert "content" in messages[0]
    assert all("content" not in m for m in messages[1:])


def test_se_recorta_y_se_avisa_de_los_omitidos():
    messages = build_messages([make_deal(i) for i in range(MAX_DEALS_PER_RUN + 7)], REALMS)

    total = sum(len(m["embeds"]) for m in messages)
    assert total == MAX_DEALS_PER_RUN
    assert "7 mas" in messages[0]["content"]


def test_reino_desconocido_se_muestra_por_su_id():
    embed = build_messages([make_deal()], {})[0]["embeds"][0]
    assert any(f["value"] == "Reino 1305" for f in embed["fields"])


def test_realm_names_for_consulta_una_vez_por_reino():
    llamadas = []

    def lookup(realm_id):
        llamadas.append(realm_id)
        return f"Reino {realm_id}"

    deals = [make_deal(1), make_deal(2), make_deal(3)]
    names = realm_names_for(deals, lookup)

    assert llamadas == [1305]
    assert names == {1305: "Reino 1305"}


def test_webhook_vacio_da_un_error_explicativo():
    with pytest.raises(DiscordError, match="DISCORD_WEBHOOK_URL"):
        DiscordNotifier("")


def test_envio_correcto(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.send_deals([make_deal()], REALMS) == 1
    assert requests_mock.call_count == 1


def test_reintenta_cuando_discord_limita_los_envios(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        [
            {"status_code": 429, "json": {"retry_after": 0.5}},
            {"status_code": 204},
        ],
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_deals([make_deal()], REALMS)

    assert esperas == [0.5]
    assert requests_mock.call_count == 2


def test_un_webhook_borrado_falla_sin_reintentar(requests_mock):
    requests_mock.post(WEBHOOK, status_code=404)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=lambda _: None)

    with pytest.raises(DiscordError, match="rechaza el webhook"):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 1


def test_se_rinde_tras_agotar_los_reintentos(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=2, sleep=lambda _: None
    )

    with pytest.raises(DiscordError):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 3


def test_mensaje_de_prueba(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    DiscordNotifier(WEBHOOK, session=requests.Session()).send_test()

    assert "Prueba de conexion" in requests_mock.last_request.json()["content"]
