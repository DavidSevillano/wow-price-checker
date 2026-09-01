"""El panel de estado que se reescribe cada hora."""

from datetime import datetime, timezone

from wowalerts.misubastas import MyAuction
from wowalerts.panel import COLOR_HAY_TRABAJO, COLOR_TODO_BIEN, build_panel
from wowalerts.undercut import Undercut


def mia(auction_id=1, personaje="Pepe", cuenta=2, objeto="Grebas", oro=9000):
    return MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name=objeto,
        ilvl=311,
        buyout_copper=oro * 10_000,
        quantity=1,
        character=personaje,
        realm="Sanguino",
        realm_slug="sanguino",
        account=cuenta,
    )


def adelantada(subasta, oro_rival=8000):
    return Undercut(
        mine=subasta,
        rival_auction_id=99,
        rival_price_copper=oro_rival * 10_000,
        rivals_ahead=1,
        realm_id=1379,
    )


def texto(panel) -> str:
    return panel["embeds"][0]["description"]


def test_sin_subastas_lo_dice_y_explica_que_hacer():
    panel = build_panel([], [])
    assert "reload" in texto(panel)


def test_cuando_todo_va_bien_el_panel_esta_verde():
    panel = build_panel([mia()], [])
    assert panel["embeds"][0]["color"] == COLOR_TODO_BIEN
    assert "todas primeras" in texto(panel)


def test_cuando_hay_trabajo_el_panel_esta_rojo():
    subasta = mia()
    panel = build_panel([subasta], [adelantada(subasta)])
    assert panel["embeds"][0]["color"] == COLOR_HAY_TRABAJO


def test_cada_personaje_lleva_su_cuenta():
    panel = build_panel([mia(personaje="Pepe", cuenta=2)], [])
    assert "Pepe · WoW 2" in texto(panel)


def test_solo_se_detallan_las_adelantadas():
    """Listar las 300 que van bien seria ilegible: lo que importa es lo que hay
    que atender."""
    subastas = [mia(i, objeto=f"Objeto {i}") for i in range(1, 6)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    assert "Objeto 1" in texto(panel)
    assert "Objeto 4" not in texto(panel)
    assert "5 vigiladas, 1 adelantada" in texto(panel)


def test_los_personajes_con_trabajo_salen_primero():
    tranquilo = mia(1, personaje="Tranquilo")
    ocupado = mia(2, personaje="Ocupado")
    panel = build_panel([tranquilo, ocupado], [adelantada(ocupado)])

    cuerpo = texto(panel)
    assert cuerpo.index("Ocupado") < cuerpo.index("Tranquilo")


def test_el_resumen_cuenta_lo_que_hay_que_atender():
    subastas = [mia(1), mia(2), mia(3)]
    panel = build_panel(subastas, [adelantada(subastas[0])])
    assert "1 de tus 3 subastas" in texto(panel)


def test_un_empate_se_dice_como_empate():
    subasta = mia(oro=9000)
    panel = build_panel([subasta], [adelantada(subasta, oro_rival=9000)])
    assert "te igualan a 9.000 g" in texto(panel)


def test_un_undercut_de_verdad_muestra_los_dos_precios():
    subasta = mia(oro=50000)
    panel = build_panel([subasta], [adelantada(subasta, oro_rival=30000)])

    assert "50.000" in texto(panel)
    assert "30.000" in texto(panel)


def test_la_hora_va_en_el_embed_para_saber_si_esta_fresco():
    cuando = datetime(2026, 8, 31, 9, 31, tzinfo=timezone.utc)
    panel = build_panel([mia()], [], cuando)
    assert panel["embeds"][0]["timestamp"] == cuando.isoformat()


def test_con_muchisimos_personajes_no_se_pasa_del_limite():
    subastas = [mia(i, personaje=f"Personaje{i}" * 4) for i in range(200)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    assert len(texto(panel)) <= 4096


def test_lo_que_se_recorta_es_siempre_lo_que_no_tiene_trabajo():
    subastas = [mia(i, personaje=f"Personaje{i}" * 4) for i in range(200)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    cuerpo = texto(panel)
    assert "Personaje0" in cuerpo
    assert "personaje(s) mas sin novedad" in cuerpo


def test_una_sola_subasta_va_en_singular():
    assert "1 vigilada," in texto(build_panel([mia()], []))


# -- Personajes con datos caducados -----------------------------------------


def test_el_panel_avisa_de_los_personajes_con_datos_muertos():
    """Si ninguna subasta suya sigue viva, el addon lleva sin visitarlos."""
    panel = build_panel([mia()], [], caducados=["Dbarfel", "Adanlin"])
    texto = panel["embeds"][0]["description"]
    assert "Dbarfel" in texto
    assert "Adanlin" in texto
    assert "/reload" in texto


def test_sin_caducados_el_panel_no_dice_nada():
    panel = build_panel([mia()], [], caducados=[])
    assert "reload" not in panel["embeds"][0]["description"]
