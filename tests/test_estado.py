from datetime import datetime, timedelta, timezone

import pytest

from estado import MINUTO_CRON, slot_de, slots_esperados


def utc(dia, hora, minuto):
    return datetime(2026, 8, dia, hora, minuto, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "inicio,slot_esperado",
    [
        # Puntual.
        (utc(30, 15, 35), utc(30, 15, 35)),
        # Con retraso, que es lo habitual en GitHub.
        (utc(30, 15, 52), utc(30, 15, 35)),
        (utc(30, 16, 34), utc(30, 15, 35)),
        # Pasada la hora siguiente, ya cuenta como el slot siguiente.
        (utc(30, 16, 35), utc(30, 16, 35)),
        # Retraso que cruza la medianoche.
        (utc(31, 0, 10), utc(30, 23, 35)),
    ],
)
def test_una_ejecucion_se_asigna_a_su_slot(inicio, slot_esperado):
    assert slot_de(inicio) == slot_esperado


def test_los_slots_esperados_son_uno_por_hora():
    esperados = slots_esperados(utc(30, 14, 31), horas=6)

    assert len(esperados) == 6
    assert all(s.minute == MINUTO_CRON for s in esperados)
    assert esperados == sorted(esperados)
    diferencias = {b - a for a, b in zip(esperados, esperados[1:])}
    assert diferencias == {timedelta(hours=1)}


def test_no_se_espera_un_slot_que_aun_no_ha_llegado():
    """A las 14:31 el slot de las 14:35 todavia no ha tocado."""
    esperados = slots_esperados(utc(30, 14, 31), horas=24)

    assert esperados[-1] == utc(30, 13, 35)


def test_el_slot_recien_cumplido_si_se_espera():
    esperados = slots_esperados(utc(30, 14, 36), horas=24)

    assert esperados[-1] == utc(30, 14, 35)


def test_la_ventana_acota_por_abajo():
    esperados = slots_esperados(utc(30, 14, 36), horas=3)

    assert esperados[0] == utc(30, 12, 35)
    assert len(esperados) == 3
