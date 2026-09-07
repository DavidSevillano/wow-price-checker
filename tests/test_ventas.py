"""La regla de deteccion de ventas, sin tocar la red."""

from datetime import datetime, timedelta, timezone

from wowalerts.misubastas import MyAuction
from wowalerts.ventas import (
    ESPERA_TRAS_UN_ADELANTAMIENTO,
    SubastaVigilada,
    UltimoVolcado,
    Venta,
    cota_por_time_left,
    revisar_reino,
)

ITEM = 200000
ORO = 10_000

# Un volcado cualquiera, para no repetir la fecha en cada test.
T0 = datetime(2026, 8, 31, 14, 31, tzinfo=timezone.utc)


def vigilada(auction_id=1, oro=9000, caduca=None, visto=None, **kwargs):
    campos = {
        "auction_id": auction_id,
        "item_id": ITEM,
        "item_name": "Greaves of the Noxious Depths",
        "ilvl": 311,
        "buyout_copper": oro * ORO,
        "quantity": 1,
        "character": "Pepe",
        "realm": "Sanguino",
        "account": 3,
        "no_caduca_antes_de": caduca if caduca is not None else T0,
        "visto_at": visto if visto is not None else T0,
    }
    campos.update(kwargs)
    return SubastaVigilada(**campos)


def test_long_garantiza_dos_horas():
    assert cota_por_time_left("LONG", T0) == T0 + timedelta(hours=2)


def test_very_long_garantiza_doce_horas():
    assert cota_por_time_left("VERY_LONG", T0) == T0 + timedelta(hours=12)


def test_medium_garantiza_media_hora():
    assert cota_por_time_left("MEDIUM", T0) == T0 + timedelta(minutes=30)


def test_short_no_garantiza_nada():
    assert cota_por_time_left("SHORT", T0) == T0


def test_un_tramo_desconocido_no_garantiza_nada():
    # Si Blizzard inventa un tramo nuevo, mejor callarse que afirmar de mas.
    assert cota_por_time_left("LO_QUE_SEA", T0) == T0


def test_el_neto_descuenta_la_comision():
    venta = Venta(
        subasta=vigilada(oro=10000), realm_id=1, detectada_at=T0, ah_cut_pct=5
    )
    assert venta.neto_gold == 9500


def test_sin_comision_el_neto_es_el_precio():
    venta = Venta(
        subasta=vigilada(oro=10000), realm_id=1, detectada_at=T0, ah_cut_pct=0
    )
    assert venta.neto_gold == 10000


# -- Seguimiento de las vivas -----------------------------------------------


def mia(auction_id=1, oro=9000, exportado=0):
    return MyAuction(
        exported_at=exportado,
        auction_id=auction_id,
        item_id=ITEM,
        item_name="Greaves of the Noxious Depths",
        ilvl=311,
        buyout_copper=oro * ORO,
        quantity=1,
        character="Pepe",
        realm="Sanguino",
        realm_slug="sanguino",
        account=3,
    )


def viva(auction_id=1, time_left="LONG"):
    return {"id": auction_id, "item": {"id": ITEM}, "time_left": time_left}


def test_una_subasta_mia_viva_entra_en_seguimiento():
    _, seguidas, _ = revisar_reino({}, [mia()], [viva()], 1, T0, None, 12, 5)
    assert 1 in seguidas
    assert seguidas[1].item_name == "Greaves of the Noxious Depths"
    assert seguidas[1].visto_at == T0


def test_la_cota_sale_del_time_left():
    _, seguidas, _ = revisar_reino({}, [mia()], [viva()], 1, T0, None, 12, 5)
    assert seguidas[1].no_caduca_antes_de == T0 + timedelta(hours=2)


def test_una_subasta_ajena_no_entra_en_seguimiento():
    _, seguidas, _ = revisar_reino(
        {}, [mia()], [viva(), viva(auction_id=999)], 1, T0, None, 12, 5
    )
    assert set(seguidas) == {1}


def test_un_id_nuevo_recibe_la_cota_de_nacimiento():
    """No estaba en la foto anterior, luego se publico despues de ella."""
    anterior = UltimoVolcado(dump_at=T0 - timedelta(hours=1), max_auction_id=500)
    _, seguidas, _ = revisar_reino(
        {}, [mia(auction_id=501)], [viva(auction_id=501)], 1, T0, anterior, 12, 5
    )
    # Nacio despues de las 13:31, asi que no caduca antes de las 01:31.
    assert seguidas[501].no_caduca_antes_de == T0 + timedelta(hours=11)


def test_un_id_viejo_no_recibe_la_cota_de_nacimiento():
    """El addon puede tardar dias en exportar una subasta.

    Que sea la primera vez que la veo no significa que sea nueva: si su id no
    supera el maximo de la foto anterior, ya existia entonces.
    """
    anterior = UltimoVolcado(dump_at=T0 - timedelta(hours=1), max_auction_id=500)
    _, seguidas, _ = revisar_reino(
        {}, [mia(auction_id=400)], [viva(auction_id=400)], 1, T0, anterior, 12, 5
    )
    assert seguidas[400].no_caduca_antes_de == T0 + timedelta(hours=2)


def test_sin_foto_anterior_no_hay_cota_de_nacimiento():
    _, seguidas, _ = revisar_reino(
        {}, [mia(auction_id=501)], [viva(auction_id=501)], 1, T0, None, 12, 5
    )
    assert seguidas[501].no_caduca_antes_de == T0 + timedelta(hours=2)


def test_un_hueco_de_tres_horas_ensancha_la_ventana():
    """Si la pasada anterior fue hace tres horas, la cota sale mas floja."""
    anterior = UltimoVolcado(dump_at=T0 - timedelta(hours=3), max_auction_id=500)
    _, seguidas, _ = revisar_reino(
        {}, [mia(auction_id=501)], [viva(auction_id=501)], 1, T0, anterior, 12, 5
    )
    assert seguidas[501].no_caduca_antes_de == T0 + timedelta(hours=9)


def test_la_cota_nunca_baja():
    """Una cota es una garantia: una posterior mas floja no la invalida."""
    previa = vigilada(caduca=T0 + timedelta(hours=10))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [mia()], [viva(time_left="MEDIUM")], 1, T0, None, 12, 5
    )
    assert seguidas[1].no_caduca_antes_de == T0 + timedelta(hours=10)


def test_la_cota_sube_cuando_el_tramo_da_mas():
    previa = vigilada(caduca=T0 + timedelta(minutes=30))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [mia()], [viva(time_left="LONG")], 1, T0, None, 12, 5
    )
    assert seguidas[1].no_caduca_antes_de == T0 + timedelta(hours=2)


def test_se_devuelve_la_foto_de_este_volcado():
    _, _, ultimo = revisar_reino(
        {}, [mia()], [viva(), viva(auction_id=999)], 1, T0, None, 12, 5
    )
    assert ultimo == UltimoVolcado(dump_at=T0, max_auction_id=999)


# -- Deteccion de la venta --------------------------------------------------

UNA_HORA_DESPUES = T0 + timedelta(hours=1)
DOS_HORAS = T0 + timedelta(hours=2)


def desaparece(seguidas, cuando=UNA_HORA_DESPUES, luego=None, **kw):
    """Dos pasadas seguidas sin aparecer, que es lo que hace falta para vender.

    La primera solo la deja pendiente; la segunda decide. Envuelto aqui porque
    lo hacen casi todos los tests de deteccion.
    """
    luego = luego if luego is not None else cuando + timedelta(hours=1)
    _, pendientes, _ = revisar_reino(seguidas, [], [], 1, cuando, None, 12, 5, **kw)
    return revisar_reino(pendientes, [], [], 1, luego, None, 12, 5, **kw)


def test_desaparecer_antes_de_poder_caducar_es_una_venta():
    # Vista en LONG a las 14:31: le quedaban 2 h como minimo. A las 15:31 ya no
    # esta, asi que no ha caducado.
    previa = vigilada(caduca=T0 + timedelta(hours=2))
    ventas, seguidas, _ = desaparece({1: previa})
    assert len(ventas) == 1
    assert ventas[0].subasta.auction_id == 1
    assert ventas[0].realm_id == 1
    assert ventas[0].detectada_at == UNA_HORA_DESPUES
    assert seguidas == {}


def test_desaparecer_pudiendo_haber_caducado_no_avisa():
    previa = vigilada(caduca=T0 + timedelta(minutes=30))
    ventas, seguidas, _ = desaparece({1: previa})
    assert ventas == []
    # Caducada o vendida, ya no existe: sale del seguimiento igualmente.
    assert seguidas == {}


def test_una_venta_no_se_repite():
    """Al salir del seguimiento, la pasada siguiente ya no la conoce."""
    previa = vigilada(caduca=T0 + timedelta(hours=2))
    _, seguidas, _ = desaparece({1: previa})
    ventas, _, _ = revisar_reino(
        seguidas, [], [], 1, T0 + timedelta(hours=3), None, 12, 5
    )
    assert ventas == []


def test_una_subasta_nunca_vista_viva_no_puede_venderse():
    """El addon tiene apuntadas subastas que hace dias que no existen.

    Sin esta guarda, la primera pasada disparia una rafaga de ventas fantasma.
    """
    ventas, seguidas, _ = revisar_reino({}, [mia()], [], 1, T0, None, 12, 5)
    assert ventas == []
    assert seguidas == {}


def test_la_venta_conserva_los_datos_aunque_el_addon_la_olvide():
    """Vendes, /reload, el sync sube el volcado ya sin ella: aun asi se anuncia."""
    previa = vigilada(caduca=T0 + timedelta(hours=2), oro=12000)
    ventas, _, _ = desaparece({1: previa})
    assert ventas[0].subasta.item_name == "Greaves of the Noxious Depths"
    assert ventas[0].subasta.character == "Pepe"
    assert ventas[0].subasta.account == 3
    assert ventas[0].neto_gold == 11400


def test_las_ventas_salen_ordenadas_por_importe():
    seguidas = {
        1: vigilada(auction_id=1, oro=5000, caduca=T0 + timedelta(hours=2)),
        2: vigilada(auction_id=2, oro=20000, caduca=T0 + timedelta(hours=2)),
    }
    ventas, _, _ = desaparece(seguidas)
    assert [v.subasta.auction_id for v in ventas] == [2, 1]


def test_la_comision_llega_a_la_venta():
    previa = vigilada(caduca=T0 + timedelta(hours=2), oro=10000)
    _, pendientes, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, ah_cut_pct=10
    )
    ventas, _, _ = revisar_reino(
        pendientes, [], [], 1, DOS_HORAS, None, 12, ah_cut_pct=10
    )
    assert ventas[0].neto_gold == 9000


def test_una_subasta_que_sigue_viva_no_es_una_venta():
    previa = vigilada(caduca=T0 + timedelta(hours=2))
    ventas, seguidas, _ = revisar_reino(
        {1: previa}, [mia()], [viva()], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    assert ventas == []
    assert set(seguidas) == {1}


def test_nacida_bajo_observacion_y_vendida_a_las_cinco_horas():
    """El caso que justifica toda la cota de nacimiento.

    A las cinco horas el tramo ya solo diria MEDIUM o SHORT, que no garantizan
    nada. Saber cuando nacio es lo que permite afirmar la venta.
    """
    anterior = UltimoVolcado(dump_at=T0 - timedelta(hours=1), max_auction_id=500)
    _, seguidas, ultimo = revisar_reino(
        {}, [mia(auction_id=501)], [viva(auction_id=501)], 1, T0, anterior, 12, 5
    )

    cinco_horas = T0 + timedelta(hours=5)
    ventas, _, _ = desaparece(seguidas, cuando=cinco_horas)
    assert len(ventas) == 1
    assert ventas[0].subasta.auction_id == 501


def test_nacida_bajo_observacion_y_desaparecida_pasadas_las_doce_horas():
    """Ya podia caducar, asi que no se afirma nada."""
    anterior = UltimoVolcado(dump_at=T0 - timedelta(hours=1), max_auction_id=500)
    _, seguidas, ultimo = revisar_reino(
        {}, [mia(auction_id=501)], [viva(auction_id=501)], 1, T0, anterior, 12, 5
    )

    doce_horas = T0 + timedelta(hours=12)
    ventas, _, _ = desaparece(seguidas, cuando=doce_horas)
    assert ventas == []


# -- La memoria en disco ----------------------------------------------------

from wowalerts.state import SeguimientoVentas


def test_un_reino_sin_estado_no_tiene_foto_anterior(tmp_path):
    memoria = SeguimientoVentas(tmp_path / "ventas.json")
    assert memoria.anterior(1305) is None
    assert memoria.del_reino(1305) == {}


def test_el_seguimiento_sobrevive_a_una_ida_y_vuelta(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(
        1305, {1: vigilada()}, UltimoVolcado(dump_at=T0, max_auction_id=900)
    )
    memoria.save(ahora=T0)

    otra = SeguimientoVentas(path)
    assert otra.anterior(1305) == UltimoVolcado(dump_at=T0, max_auction_id=900)
    recuperada = otra.del_reino(1305)[1]
    assert recuperada == vigilada()
    assert recuperada.no_caduca_antes_de.tzinfo is not None


def test_cada_reino_guarda_lo_suyo(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(1, {1: vigilada()}, UltimoVolcado(T0, 900))
    memoria.actualizar_reino(2, {2: vigilada(auction_id=2)}, UltimoVolcado(T0, 800))
    memoria.save(ahora=T0)

    otra = SeguimientoVentas(path)
    assert set(otra.del_reino(1)) == {1}
    assert set(otra.del_reino(2)) == {2}


def test_se_olvidan_las_entradas_de_hace_mas_de_una_semana(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    viejo = T0 - timedelta(days=8)
    memoria.actualizar_reino(
        1,
        {1: vigilada(visto=viejo), 2: vigilada(auction_id=2)},
        UltimoVolcado(T0, 900),
    )
    memoria.save(ahora=T0)

    assert set(SeguimientoVentas(path).del_reino(1)) == {2}


def test_un_fichero_corrupto_no_tumba_la_pasada(tmp_path):
    path = tmp_path / "ventas.json"
    path.write_text("{esto no es json", encoding="utf-8")
    memoria = SeguimientoVentas(path)
    assert memoria.del_reino(1) == {}
    assert memoria.anterior(1) is None


def test_una_entrada_ilegible_se_descarta_sin_romper(tmp_path):
    path = tmp_path / "ventas.json"
    path.write_text(
        '{"version": 1, "realms": {}, "seguimiento": {"1:5": {"item_id": 1}}}',
        encoding="utf-8",
    )
    assert SeguimientoVentas(path).del_reino(1) == {}


def test_los_reinos_con_seguimiento_se_saben(tmp_path):
    """Hay que volver a un reino aunque el addon ya no mencione nada alli."""
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(1305, {1: vigilada()}, UltimoVolcado(T0, 900))
    memoria.actualizar_reino(1378, {2: vigilada(auction_id=2)}, UltimoVolcado(T0, 800))
    memoria.save(ahora=T0)

    assert SeguimientoVentas(path).reinos_con_seguimiento() == {1305, 1378}


def test_un_reino_ya_resuelto_deja_de_mirarse(tmp_path):
    """Las entradas salen solas al resolverse, asi que la lista se vacia."""
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(1305, {1: vigilada()}, UltimoVolcado(T0, 900))
    memoria.actualizar_reino(1305, {}, UltimoVolcado(T0, 900))
    memoria.save(ahora=T0)

    assert SeguimientoVentas(path).reinos_con_seguimiento() == set()


# -- Reposteos tras un aviso de undercut ------------------------------------


def test_una_adelantada_que_desaparece_se_espera_pero_no_se_descarta():
    """Que te adelanten no prueba que hayas ido a repostear.

    El aviso te manda a repostear, pero puedes no haber ido --de madrugada,
    sin ir mas lejos-- y una subasta adelantada se vende igual. Descartarla
    para siempre se comia ventas de verdad: el 2026-09-06 se trago las 38.002 g
    de un Yelmo mistico que Journalator tenia apuntado como vendido.
    """
    previa = vigilada(
        caduca=T0 + timedelta(hours=5), adelantada=True, desaparecida_at=T0
    )
    ventas, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    assert ventas == []
    # Lo importante: sigue en seguimiento, no se ha tirado.
    assert seguidas[1].desaparecida_at == T0


def test_la_marca_de_adelantada_se_pone_al_verla_viva():
    _, seguidas, _ = revisar_reino(
        {}, [mia()], [viva()], 1, T0, None, 12, 5, adelantadas={1}
    )
    assert seguidas[1].adelantada is True


def test_sin_undercut_la_marca_se_quita():
    """Si el rival se va, la subasta deja de estar adelantada."""
    previa = vigilada(adelantada=True)
    _, seguidas, _ = revisar_reino(
        {1: previa}, [mia()], [viva()], 1, T0, None, 12, 5, adelantadas=set()
    )
    assert seguidas[1].adelantada is False


def test_dejar_de_estar_adelantada_devuelve_la_deteccion_de_venta():
    """La supresion dura solo la ventana en la que reposteas.

    Adelantada en una pasada, ya no en la siguiente: si desaparece despues, es
    una venta y se avisa.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=5), adelantada=True)
    _, seguidas, _ = revisar_reino(
        {1: previa}, [mia()], [viva()], 1, T0, None, 12, 5, adelantadas=set()
    )
    ventas, _, _ = desaparece(seguidas)
    assert len(ventas) == 1


def test_si_el_addon_ya_no_la_conoce_se_conserva_la_marca():
    """Sin datos para recalcular el undercut, no se borra lo que ya sabia.

    Callarse de mas es preferible a inventarse una venta.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=5), adelantada=True)
    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [viva()], 1, T0, None, 12, 5, adelantadas=set()
    )
    assert seguidas[1].adelantada is True


def test_la_marca_sobrevive_al_disco(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(
        1, {1: vigilada(adelantada=True)}, UltimoVolcado(T0, 900)
    )
    memoria.save(ahora=T0)
    assert SeguimientoVentas(path).del_reino(1)[1].adelantada is True


def test_la_espera_por_un_adelantamiento_se_deja_por_escrito(caplog):
    """Sin esta linea no se distingue 'no has vendido' de 'estoy esperando'."""
    import logging

    previa = vigilada(
        caduca=T0 + timedelta(hours=5), adelantada=True, desaparecida_at=T0
    )
    with caplog.at_level(logging.INFO, logger="wowalerts.ventas"):
        revisar_reino({1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5)

    assert "adelantando" in caplog.text
    assert "Pepe" in caplog.text


# -- Espera de una pasada y lista de cancelaciones --------------------------

DOS_HORAS_DESPUES = T0 + timedelta(hours=2)


def test_desaparecer_no_se_canta_en_la_misma_pasada():
    """Se espera una pasada por si llega la cancelacion desde el juego."""
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    ventas, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    assert ventas == []
    # Sigue en seguimiento, pero anotada como desaparecida.
    assert seguidas[1].desaparecida_at == UNA_HORA_DESPUES


def test_si_sigue_sin_aparecer_en_la_siguiente_se_canta():
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    ventas, quedan, _ = revisar_reino(
        seguidas, [], [], 1, DOS_HORAS_DESPUES, None, 12, 5
    )
    assert len(ventas) == 1
    assert quedan == {}


def test_la_caducidad_se_juzga_por_cuando_desaparecio():
    """El dato es el momento en que se fue, no el de la pasada que decide.

    Sin esto, la espera de una pasada empujaria a la subasta mas alla de su
    fecha de caducidad y se perderian ventas buenas.
    """
    # Cota justo entre la desaparicion (T0+1h) y la decision (T0+2h).
    previa = vigilada(caduca=T0 + timedelta(hours=2))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    ventas, _, _ = revisar_reino(
        seguidas, [], [], 1, DOS_HORAS_DESPUES, None, 12, 5
    )
    assert len(ventas) == 1
    assert ventas[0].detectada_at == UNA_HORA_DESPUES


def test_una_cancelacion_que_llega_a_tiempo_evita_el_aviso():
    """El caso que motiva toda la espera."""
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    ventas, quedan, _ = revisar_reino(
        seguidas, [], [], 1, DOS_HORAS_DESPUES, None, 12, 5, canceladas={1}
    )
    assert ventas == []
    assert quedan == {}


def test_una_cancelacion_ya_conocida_se_descarta_sin_esperar():
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    ventas, quedan, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5, canceladas={1}
    )
    assert ventas == []
    assert quedan == {}


def test_una_pendiente_que_reaparece_deja_de_estarlo():
    """Un reino que fallo, o un volcado raro: si vuelve, no se ha vendido."""
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    assert seguidas[1].desaparecida_at is not None
    _, vuelta, _ = revisar_reino(
        seguidas, [mia()], [viva()], 1, DOS_HORAS_DESPUES, None, 12, 5
    )
    assert vuelta[1].desaparecida_at is None


def test_una_adelantada_se_canta_cuando_vence_la_espera():
    """Cancelarla exige jugar, y jugar acaba escribiendo los SavedVariables.

    Si en dos horas el addon no ha vuelto a hablar, es que no has jugado, y
    entonces no la has podido cancelar: se vendio.
    """
    previa = vigilada(
        caduca=T0 + timedelta(hours=5), adelantada=True, desaparecida_at=T0
    )
    ventas, _, _ = revisar_reino(
        {1: previa}, [], [], 1, T0 + ESPERA_TRAS_UN_ADELANTAMIENTO, None, 12, 5
    )
    assert len(ventas) == 1


def test_una_adelantada_se_canta_en_cuanto_el_addon_vuelve_a_hablar():
    """No hace falta agotar la espera si ya hay respuesta.

    Un volcado del addon posterior a la desaparicion que no la lista como
    cancelada es todo lo que se necesita saber.
    """
    previa = vigilada(
        caduca=T0 + timedelta(hours=5), adelantada=True, desaparecida_at=T0
    )
    despues = mia(auction_id=2, exportado=int((T0 + timedelta(minutes=30)).timestamp()))
    ventas, _, _ = revisar_reino(
        {1: previa}, [despues], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    assert len(ventas) == 1


def test_si_el_addon_dice_que_la_cancelaste_no_es_venta_aunque_venza_la_espera():
    previa = vigilada(
        caduca=T0 + timedelta(hours=5), adelantada=True, desaparecida_at=T0
    )
    ventas, quedan, _ = revisar_reino(
        {1: previa}, [], [], 1, T0 + ESPERA_TRAS_UN_ADELANTAMIENTO, None, 12, 5,
        canceladas={1},
    )
    assert ventas == []
    assert quedan == {}


def test_la_marca_de_desaparicion_sobrevive_al_disco(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(
        1, {1: vigilada(desaparecida_at=T0)}, UltimoVolcado(T0, 900)
    )
    memoria.save(ahora=T0)
    assert SeguimientoVentas(path).del_reino(1)[1].desaparecida_at == T0


def test_la_venta_dice_de_que_ilvl_era():
    """Con el mismo objeto a 292, 295 y 305, sin el ilvl no sabes cual se fue."""
    previa = vigilada(caduca=T0 + timedelta(hours=2), ilvl=295)
    ventas, _, _ = desaparece({1: previa})
    assert ventas[0].subasta.ilvl == 295


def test_el_ilvl_se_copia_de_la_subasta_del_addon():
    _, seguidas, _ = revisar_reino({}, [mia()], [viva()], 1, T0, None, 12, 5)
    assert seguidas[1].ilvl == 311


def test_el_ilvl_sobrevive_al_disco(tmp_path):
    path = tmp_path / "ventas.json"
    memoria = SeguimientoVentas(path)
    memoria.actualizar_reino(1, {1: vigilada(ilvl=298)}, UltimoVolcado(T0, 900))
    memoria.save(ahora=T0)
    assert SeguimientoVentas(path).del_reino(1)[1].ilvl == 298


def test_en_silencio_no_se_decide_nada_todavia():
    """La subasta queda pendiente hasta que acabe la ventana.

    Asi la venta se anuncia al despertar, y con la hora en la que desaparecio
    de verdad, no con la de la pasada que la decide.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, pendientes, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    ventas, siguen, _ = revisar_reino(
        pendientes, [], [], 1, DOS_HORAS, None, 12, 5, decidir=False
    )
    assert ventas == []
    # Sigue pendiente, con su hora original intacta.
    assert siguen[1].desaparecida_at == UNA_HORA_DESPUES


def test_al_acabar_el_silencio_se_decide_con_la_hora_buena():
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, pendientes, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5
    )
    _, siguen, _ = revisar_reino(
        pendientes, [], [], 1, DOS_HORAS, None, 12, 5, decidir=False
    )
    ventas, _, _ = revisar_reino(
        siguen, [], [], 1, T0 + timedelta(hours=8), None, 12, 5
    )
    assert len(ventas) == 1
    assert ventas[0].detectada_at == UNA_HORA_DESPUES


# ---------------------------------------------------------------------------
#  Subastas de una maquina que dejo de exportar
# ---------------------------------------------------------------------------
#
#  El 2026-09-02 la Steam Deck paso 16 horas sin exportar. Sus subastas se
#  habian relistado con ids nuevos, y al no encontrar los viejos en los datos de
#  Blizzard se cantaron como vendidas dos que seguian puestas. El volcado dice
#  que subastas son tuyas, pero esa afirmacion caduca.


def test_una_subasta_de_volcado_viejo_se_suelta_sin_veredicto():
    """Lo importante: se deja de seguir, pero NO se canta como venta."""
    previa = vigilada(caduca=T0 + timedelta(hours=2))

    ventas, seguidas, _ = desaparece({1: previa}, olvidar={1})

    assert ventas == []
    assert seguidas == {}


def test_olvidar_solo_afecta_a_las_senaladas():
    """La maquina que si esta al dia tiene que seguir detectando sus ventas."""
    dos = vigilada(auction_id=2, caduca=T0 + timedelta(hours=2))

    ventas, _, _ = desaparece(
        {1: vigilada(caduca=T0 + timedelta(hours=2)), 2: dos}, olvidar={1}
    )

    assert [v.subasta.auction_id for v in ventas] == [2]


def test_una_de_volcado_viejo_que_blizzard_sigue_viendo_no_se_suelta():
    """El volcado del addon envejece; que Blizzard la liste, no.

    Su fecha de caducidad se mantiene con el time_left que manda Blizzard, que
    no depende del addon para nada. Soltarla igual tiraba la unica prueba buena
    que hay: el 2026-09-06 se llevo por delante un Yelmo mistico de Ebardan
    de 190.000 g, vendido de verdad y jamas anunciado.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=2))

    _, seguidas, _ = revisar_reino(
        {1: previa}, [], [viva()], 1, UNA_HORA_DESPUES, None, 12, 5, olvidar={1}
    )

    assert 1 in seguidas


def test_y_si_luego_desaparece_se_canta_como_venta():
    """Seguirla sirve de poco si al irse no se decide nada."""
    previa = vigilada(caduca=T0 + timedelta(hours=5))
    _, seguidas, foto = revisar_reino(
        {1: previa}, [], [viva()], 1, UNA_HORA_DESPUES, None, 12, 5, olvidar={1}
    )

    # Se va, y con el volcado del addon igual de viejo que antes.
    _, seguidas, foto = revisar_reino(
        seguidas, [], [], 1, DOS_HORAS_DESPUES, foto, 12, 5, olvidar={1}
    )
    ventas, _, _ = revisar_reino(
        seguidas, [], [], 1, T0 + timedelta(hours=3), foto, 12, 5, olvidar={1}
    )

    assert len(ventas) == 1


def test_un_id_zombi_de_volcado_viejo_se_sigue_soltando():
    """La guarda original: lo peligroso es lo que el addon canta y Blizzard no.

    Es lo que el 2026-09-02 invento dos ventas de Dbardan.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=2))

    ventas, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, UNA_HORA_DESPUES, None, 12, 5, olvidar={1}
    )

    assert ventas == []
    assert seguidas == {}


def test_un_zombi_que_lleva_dos_pasadas_sin_aparecer_se_suelta():
    """La guarda tiene que aguantar aunque haya foto anterior.

    Visto vivo por ultima vez hace mas de una pasada y con el volcado del addon
    caducado: de eso no se puede afirmar nada, y afirmar de mas inventa ventas.
    """
    previa = vigilada(caduca=T0 + timedelta(hours=5), visto=T0)
    foto_anterior = UltimoVolcado(UNA_HORA_DESPUES, 900)

    ventas, seguidas, _ = revisar_reino(
        {1: previa}, [], [], 1, DOS_HORAS_DESPUES, foto_anterior, 12, 5, olvidar={1}
    )

    assert ventas == []
    assert seguidas == {}
