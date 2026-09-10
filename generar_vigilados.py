"""Genera addon/WowAlertsExport/Vigilados.lua a partir de config.yaml.

    py generar_vigilados.py

El addon no puede leer config.yaml: WoW solo carga los ficheros Lua que lista
el .toc. Este script le pasa lo que el reposteo necesita --que objetos
repostear, que personajes son tuyos y con que duracion postear-- y el fichero
se sube a git, porque en la Steam Deck no hay credenciales de Blizzard con las
que resolver los ids.

Vuelve a ejecutarlo cada vez que cambies los objetos, orden_personajes o
listing_hours. Un test falla si se te olvida.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardClient
from wowalerts.config import ConfigError, ItemRule, load_config
from wowalerts.items import ItemResolutionError, resolve_item_ids
from wowalerts.state import ItemIdCache

log = logging.getLogger("vigilados")

EXIT_OK = 0
EXIT_ERROR = 1

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "addon" / "WowAlertsExport" / "Vigilados.lua"

# La casa de subastas solo admite estas duraciones, y PostItem las pide por
# numero: 1 son 12 horas, 2 son 24 y 3 son 48.
DURACIONES = {12: 1, 24: 2, 48: 3}


def duracion_de(listing_hours: int) -> int:
    """El numero de duracion que entiende PostItem."""
    if listing_hours not in DURACIONES:
        raise ConfigError(
            f"'listing_hours' vale {listing_hours}, y la casa de subastas solo "
            "admite 12, 24 o 48 horas: el reposteo no sabria con que duracion "
            "postear."
        )
    return DURACIONES[listing_hours]


def objetos_a_repostear(reglas: Mapping[int, ItemRule]) -> dict[int, str]:
    """{item_id: nombre} de los objetos con avisos de undercut.

    Las mascotas se quedan fuera: en la casa todas son la misma jaula.
    """
    return {
        item_id: regla.name
        for item_id, regla in sorted(reglas.items())
        if regla.avisar_undercut and not regla.es_mascota
    }


def _cadena_lua(texto: str) -> str:
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def a_lua(objetos: Mapping[int, str], personajes: Sequence[str], duracion: int) -> str:
    """El contenido de Vigilados.lua."""
    lineas = [
        "-- Generado por generar_vigilados.py a partir de config.yaml.",
        "-- No lo edites a mano: vuelve a ejecutar el script.",
        "",
        "WowAlertsVigilados = {",
        "    objetos = {",
    ]
    for item_id, nombre in sorted(objetos.items()):
        lineas.append(f"        [{item_id}] = {_cadena_lua(nombre)},")
    lineas += ["    },", "    personajes = {"]
    for nombre in personajes:
        lineas.append(f"        {_cadena_lua(nombre)},")
    lineas += ["    },", f"    duracion = {duracion},", "}"]
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(RAIZ / "config.yaml"))
    parser.add_argument("--state-dir", default=str(RAIZ / ".state"))
    parser.add_argument("--salida", default=str(DESTINO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(RAIZ / ".env")

    try:
        config = load_config(args.config)
        duracion = duracion_de(config.settings.listing_hours)
    except ConfigError as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR

    client = BlizzardClient(
        client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
        client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )
    cache = ItemIdCache(Path(args.state_dir) / "item_ids.json")
    try:
        reglas = resolve_item_ids(client, config, cache)
    except ItemResolutionError as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR
    cache.save()

    texto = a_lua(objetos_a_repostear(reglas), config.orden_personajes, duracion)
    salida = Path(args.salida)
    if salida.is_file() and salida.read_text(encoding="utf-8") == texto:
        log.info("Vigilados.lua ya estaba al dia.")
        return EXIT_OK

    # newline="\n": el mismo fichero byte a byte en Windows y en la Deck.
    salida.write_text(texto, encoding="utf-8", newline="\n")
    log.info("✅ Escrito %s.", salida)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
