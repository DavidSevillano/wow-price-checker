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

    deal = make_deal()
    assert notifier.send_deals([deal], REALMS) == [deal]
    assert requests_mock.call_count == 1


def test_send_deals_devuelve_solo_lo_que_ha_salido(requests_mock):
    """Con mas chollos de los que caben, devuelve unicamente los enviados.

    Quien llama marca como avisados los devueltos: si devolviera todos, los
    que no cupieron quedarian marcados sin haberse enviado y no volverian a
    notificarse nunca.
    """
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    deals = [make_deal(auction_id=i) for i in range(MAX_DEALS_PER_RUN + 7)]

    enviados = notifier.send_deals(deals, REALMS)

    assert len(enviados) == MAX_DEALS_PER_RUN
    assert enviados == deals[:MAX_DEALS_PER_RUN]


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


# -- Avisos de undercut -----------------------------------------------------

from wowalerts.misubastas import MyAuction
from wowalerts.notifier import COLOR_UNDERCUT, build_undercut_messages
from wowalerts.undercut import Undercut


def un_undercut(
    objeto="Grebas de las profundidades nocivas",
    oro_mio=9000,
    oro_rival=8000,
    personaje="Pepe",
    reino="Sanguino",
    cuenta=2,
    auction_id=1,
):
    mine = MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name=objeto,
        ilvl=311,
        buyout_copper=oro_mio * 10_000,
        quantity=1,
        character=personaje,
        realm=reino,
        realm_slug=reino.lower(),
        account=cuenta,
    )
    return Undercut(
        mine=mine,
        realm_id=1379,
        rival_auction_id=99,
        rival_price_copper=oro_rival * 10_000,
        rivals_ahead=1,
    )


def texto(mensaje) -> str:
    """Titulo y descripcion de la tarjeta, juntos, para poder buscar en ellos."""
    embed = mensaje["embeds"][0]
    return embed["title"] + "\n" + embed["description"]


def test_sin_undercuts_no_hay_mensajes():
    assert build_undercut_messages([]) == []


def test_la_cabecera_lleva_personaje_y_cuenta():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "Pepe" in contenido
    assert "WoW 2" in contenido


def test_la_cabecera_no_lleva_el_reino():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "Sanguino" not in contenido


def test_sin_cuenta_conocida_solo_va_el_personaje():
    contenido = texto(build_undercut_messages([un_undercut(cuenta=None)])[0])
    assert "Pepe" in contenido
    assert "WoW" not in contenido


def test_el_mismo_personaje_en_cuentas_distintas_son_mensajes_distintos():
    mensajes = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", cuenta=1, auction_id=1),
            un_undercut(personaje="Pepe", cuenta=3, auction_id=2),
        ]
    )
    assert len(mensajes) == 2


def test_un_mensaje_por_personaje():
    mensajes = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", auction_id=1),
            un_undercut(personaje="Ana", auction_id=2),
            un_undercut(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 2
    assert "Pepe" in texto(mensajes[0])
    assert "Ana" in texto(mensajes[1])


def test_las_subastas_de_un_personaje_van_juntas():
    mensajes = build_undercut_messages(
        [
            un_undercut(objeto="Grebas", personaje="Pepe", auction_id=1),
            un_undercut(objeto="Zapatillas", personaje="Pepe", auction_id=2),
        ]
    )
    assert len(mensajes) == 1
    assert "Grebas" in texto(mensajes[0])
    assert "Zapatillas" in texto(mensajes[0])


def test_un_undercut_de_verdad_muestra_los_dos_precios():
    contenido = texto(
        build_undercut_messages([un_undercut(oro_mio=50000, oro_rival=30000)])[0]
    )
    assert "50.000" in contenido
    assert "30.000" in contenido


def test_un_empate_se_dice_como_empate():
    contenido = texto(
        build_undercut_messages([un_undercut(oro_mio=9000, oro_rival=9000)])[0]
    )
    assert "igualan" in contenido
    assert "9.000" in contenido


def test_el_recuento_va_en_la_cabecera():
    mensajes = build_undercut_messages(
        [un_undercut(auction_id=1), un_undercut(auction_id=2)]
    )
    assert "2 nuevas" in texto(mensajes[0])


def test_una_sola_subasta_va_en_singular():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "1 nueva" in contenido
    assert "nuevas" not in contenido


def test_el_recuento_dice_que_son_solo_las_nuevas():
    """"1 subasta" se leia como el total del personaje, y no lo es."""
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "nueva" in contenido


def test_se_avisa_de_las_que_ya_estaban_avisadas():
    """Si no, ves "1 nueva" y crees que ese personaje solo tiene una."""
    ya = [un_undercut(personaje="Ana", objeto="Grebas", auction_id=7)]
    mensajes = build_undercut_messages([un_undercut()], ya_avisados=ya)
    assert "1" in mensajes[0]["content"]


def test_las_ya_avisadas_se_nombran():
    """Un recuento a secas no sirve para nada: hay que decir cuales son."""
    ya = [un_undercut(personaje="Ana", objeto="Zapatillas", auction_id=7)]
    contenido = build_undercut_messages([un_undercut()], ya_avisados=ya)[0]["content"]
    assert "Ana" in contenido
    assert "Zapatillas" in contenido


def test_una_lista_larga_de_ya_avisadas_se_recorta():
    ya = [
        un_undercut(personaje=f"Pj{i}", objeto="Grebas", auction_id=100 + i)
        for i in range(12)
    ]
    contenido = build_undercut_messages([un_undercut()], ya_avisados=ya)[0]["content"]
    assert "panel" in contenido.lower()
    assert "Pj0" in contenido
    # No caben las doce: se nombran unas cuantas y se dice cuantas faltan.
    assert "Pj11" not in contenido


def test_sin_repetidos_no_se_anade_nada():
    mensajes = build_undercut_messages([un_undercut()], ya_avisados=[])
    assert "content" not in mensajes[0]


def test_un_personaje_con_muchisimas_se_parte_en_varios_mensajes():
    muchas = [un_undercut(auction_id=i) for i in range(1, 26)]
    mensajes = build_undercut_messages(muchas)
    assert len(mensajes) == 2
    assert "Pepe" in texto(mensajes[1])


def test_cada_mensaje_es_una_tarjeta_con_su_color():
    mensaje = build_undercut_messages([un_undercut()])[0]
    assert len(mensaje["embeds"]) == 1
    assert mensaje["embeds"][0]["color"] == COLOR_UNDERCUT


def test_ninguna_tarjeta_pasa_de_los_limites_de_discord():
    muchas = [
        un_undercut(objeto="Objeto con un nombre larguisimo " * 3, auction_id=i)
        for i in range(1, 51)
    ]
    for mensaje in build_undercut_messages(muchas):
        embed = mensaje["embeds"][0]
        assert len(embed["description"]) <= 4096
        assert len(embed["title"]) <= 256


# -- Panel de estado --------------------------------------------------------

from wowalerts.notifier import build_undercut_messages as _bum  # noqa: F401

PANEL = {"embeds": [{"title": "📊 Tus subastas"}]}


def test_el_panel_se_crea_la_primera_vez_y_devuelve_su_id(requests_mock):
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "12345"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) == "12345"


def test_el_panel_reescribe_el_mensaje_que_ya_existe(requests_mock):
    editar = requests_mock.patch(WEBHOOK + "/messages/12345", status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "12345") == "12345"
    assert editar.call_count == 1


def test_si_el_mensaje_del_panel_ya_no_existe_se_crea_otro(requests_mock):
    """Lo puedes haber borrado, o haberse perdido la memoria entre pasadas."""
    requests_mock.patch(WEBHOOK + "/messages/viejo", status_code=404)
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "nuevo"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "viejo") == "nuevo"


def test_un_fallo_del_panel_no_tumba_la_pasada(requests_mock):
    """El panel es un extra; los avisos son lo importante."""
    requests_mock.post(WEBHOOK + "?wait=true", status_code=500)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) is None


# -- Avisos de venta --------------------------------------------------------

from datetime import datetime, timezone

from wowalerts.notifier import COLOR_VENTA, build_venta_messages
from wowalerts.ventas import SubastaVigilada, Venta

CUANDO = datetime(2026, 8, 31, 14, 31, tzinfo=timezone.utc)


def una_venta(
    objeto="Grebas de las profundidades nocivas",
    personaje="Pepe",
    cuenta=3,
    oro=10000,
    auction_id=1,
    cantidad=1,
):
    return Venta(
        subasta=SubastaVigilada(
            auction_id=auction_id,
            item_id=200000,
            item_name=objeto,
            buyout_copper=oro * 10_000,
            quantity=cantidad,
            character=personaje,
            realm="Sanguino",
            account=cuenta,
            no_caduca_antes_de=CUANDO,
            visto_at=CUANDO,
        ),
        realm_id=1305,
        detectada_at=CUANDO,
        ah_cut_pct=5,
    )


def test_sin_ventas_no_hay_mensajes():
    assert build_venta_messages([]) == []


def test_una_venta_muestra_el_neto():
    contenido = texto(build_venta_messages([una_venta(oro=10000)])[0])
    assert "9.500 g" in contenido


def test_el_titulo_lleva_personaje_y_cuenta():
    mensaje = build_venta_messages([una_venta()])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe · WoW 3 — 1 venta"


def test_sin_cuenta_el_titulo_solo_lleva_el_personaje():
    mensaje = build_venta_messages([una_venta(cuenta=None)])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe — 1 venta"


def test_una_sola_venta_no_lleva_total():
    contenido = texto(build_venta_messages([una_venta()])[0])
    assert "Total" not in contenido


def test_varias_ventas_del_mismo_personaje_llevan_total():
    mensajes = build_venta_messages(
        [
            una_venta(objeto="Grebas", oro=10000, auction_id=1),
            una_venta(objeto="Zapatillas", oro=20000, auction_id=2),
        ]
    )
    assert len(mensajes) == 1
    # 9.500 + 19.000
    assert "Total: 28.500 g" in texto(mensajes[0])


def test_cada_personaje_va_en_su_mensaje():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", auction_id=1),
            una_venta(personaje="Ana", auction_id=2),
            una_venta(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 2


def test_el_mismo_nombre_en_cuentas_distintas_no_se_mezcla():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", cuenta=1, auction_id=1),
            una_venta(personaje="Pepe", cuenta=3, auction_id=2),
        ]
    )
    assert len(mensajes) == 2


def test_el_embed_lleva_color_y_hora_del_volcado():
    embed = build_venta_messages([una_venta()])[0]["embeds"][0]
    assert embed["color"] == COLOR_VENTA
    assert embed["timestamp"] == CUANDO.isoformat()


def test_una_venta_de_varias_unidades_lo_dice():
    contenido = texto(build_venta_messages([una_venta(cantidad=5)])[0])
    assert "×5" in contenido


def test_muchas_ventas_de_un_personaje_se_trocean():
    """Discord tiene un tope por mensaje; el segundo se marca como sigue."""
    muchas = [una_venta(auction_id=i) for i in range(25)]
    mensajes = build_venta_messages(muchas)
    assert len(mensajes) > 1
    assert mensajes[1]["embeds"][0]["title"] == "💰 Pepe · WoW 3 · sigue"
