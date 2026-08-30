"""Saber si los datos de subastas que hemos leido son los de esta hora.

Blizzard regenera la casa de subastas una vez por hora y para toda la region a
la vez, y lo publica hacia el minuto 31. El cron dispara poco despues, asi que
casi siempre leemos el volcado recien salido. Pero si Blizzard se retrasa unos
minutos, la pasada se encuentra todavia con los datos de la hora anterior: ya
los miramos, no traen nada nuevo, y hasta la hora siguiente no habria otra
oportunidad.

Aqui se decide si merece la pena esperar y volver a mirar.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Minuto en el que Blizzard publica el volcado. Medido en EU durante varias
# horas seguidas; si algun dia se desplaza, el log de cada pasada canta la
# antiguedad del volcado y este numero se ajusta desde config.yaml.
DUMP_MINUTE = 31


def expected_dump_at(now: datetime, minute: int = DUMP_MINUTE) -> datetime:
    """Ultimo volcado que Blizzard ya deberia haber publicado a estas horas."""
    esperado = now.replace(minute=minute, second=0, microsecond=0)
    if esperado > now:
        esperado -= timedelta(hours=1)
    return esperado


def dump_is_stale(
    snapshot_at: datetime | None,
    now: datetime,
    minute: int = DUMP_MINUTE,
) -> bool:
    """True si el volcado que hemos leido es anterior al que ya tocaba.

    Compara contra el horario de Blizzard, no contra una antiguedad fija: a las
    12:58 un volcado de las 12:31 tiene 27 minutos y aun asi es el ultimo que
    existe, de modo que esperar no serviria de nada.

    Sin `snapshot_at` no hay nada que comparar. Eso pasa cuando ningun reino ha
    respondido, y entonces el problema no es el horario: reintentar solo
    gastaria tiempo.
    """
    if snapshot_at is None:
        return False
    return snapshot_at < expected_dump_at(now, minute)
