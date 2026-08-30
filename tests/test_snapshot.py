from datetime import datetime, timedelta, timezone

import pytest

from wowalerts.snapshot import dump_is_stale, expected_dump_at

# Blizzard publica hacia el minuto 31; los tests lo fijan aparte para no
# romperse si cambia el valor por defecto.
MIN = 31


def utc(dia, hora, minuto):
    return datetime(2026, 8, dia, hora, minuto, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "ahora,esperado",
    [
        # Justo despues del volcado, que es cuando corre el cron.
        (utc(30, 13, 33), utc(30, 13, 31)),
        # En el minuto exacto ya se da por publicado.
        (utc(30, 13, MIN), utc(30, 13, MIN)),
        # Antes del volcado de esta hora, el vigente es el de la anterior.
        (utc(30, 13, 30), utc(30, 12, MIN)),
        (utc(30, 13, 0), utc(30, 12, MIN)),
        # Cruzando la medianoche.
        (utc(31, 0, 10), utc(30, 23, MIN)),
    ],
)
def test_el_volcado_vigente_es_el_ultimo_ya_publicado(ahora, esperado):
    assert expected_dump_at(ahora, minute=MIN) == esperado


def test_el_volcado_de_esta_hora_no_esta_viejo():
    assert not dump_is_stale(utc(30, 13, MIN), utc(30, 13, 33), minute=MIN)


def test_el_volcado_de_la_hora_anterior_si_lo_esta():
    """El caso que motiva el reintento: Blizzard va tarde y seguimos con datos viejos."""
    assert dump_is_stale(utc(30, 12, MIN), utc(30, 13, 33), minute=MIN)


def test_una_pasada_a_mano_a_media_hora_no_cuenta_como_vieja():
    """A y 58 el volcado de y 31 tiene 27 min, pero es el ultimo que existe."""
    assert not dump_is_stale(utc(30, 12, MIN), utc(30, 12, 58), minute=MIN)


def test_una_pasada_antes_del_volcado_tampoco():
    assert not dump_is_stale(utc(30, 12, MIN), utc(30, 13, 10), minute=MIN)


def test_un_volcado_adelantado_no_es_viejo():
    assert not dump_is_stale(utc(30, 13, 45), utc(30, 13, 50), minute=MIN)


def test_sin_marca_de_tiempo_no_se_reintenta():
    """Si ningun reino dio Last-Modified, el problema es otro y esperar no ayuda."""
    assert not dump_is_stale(None, utc(30, 13, 33), minute=MIN)


def test_el_minuto_por_defecto_es_el_de_blizzard():
    from wowalerts.snapshot import DUMP_MINUTE

    assert expected_dump_at(utc(30, 13, 59)).minute == DUMP_MINUTE
    assert timedelta(0) <= utc(30, 13, 59) - expected_dump_at(utc(30, 13, 59))
