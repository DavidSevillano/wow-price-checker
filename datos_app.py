"""Genera los ficheros que consume la app del movil.

    py datos_app.py                    # a publicar/
    py datos_app.py --salida /tmp/x    # a otra carpeta
    py datos_app.py --solo-catalogo    # sin bajarse ningun reino

Publica dos cosas:

  catalogo.json   que objetos vigilas, como se llaman en espanol, su icono y tu
                  tabla de precios por ilvl. Cambia solo cuando tocas
                  config.yaml, pero se regenera igual en cada pasada porque
                  cuesta cuatro peticiones y asi la app nunca se queda atras.

  precios.json    el mas barato de cada objeto e ilvl en los reinos donde
                  vendes. Es el dato que no sobrevive a la pasada: el volcado de
                  un reino son decenas de miles de subastas que se miran y se
                  tiran.

Va aparte de main.py a proposito. main.py es el que te manda las alertas y no
conviene tocarlo para esto; ademas, aqui solo se bajan los veinte y pico reinos
donde tienes personajes, no los 92 de la region.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardClient, BlizzardError
from wowalerts.config import ConfigError, load_config
from wowalerts.items import ItemResolutionError, resolve_item_ids
from wowalerts.misubastas import slugify_realm
from wowalerts.personajes import leer_rosters
from wowalerts.precios import construir_precios, minimos_del_reino, reinos_a_vigilar
from wowalerts.realms import resolve_connected_realms
from wowalerts.state import ItemIdCache, RealmIdCache

log = logging.getLogger("datos_app")

EXIT_OK = 0
EXIT_ERROR = 1

# Blizzard clasifica las monturas como "Miscelanea > Montura".
CLASE_MISCELANEA = 15
SUBCLASE_MONTURA = 5

CATALOGO_VERSION = 1


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera catalogo.json y precios.json para la app del movil.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--state-dir", default=".state")
    parser.add_argument("--personajes", default="mis_personajes")
    parser.add_argument(
        "--salida",
        default="publicar",
        help="Carpeta donde escribir los ficheros (por defecto: publicar).",
    )
    parser.add_argument(
        "--solo-catalogo",
        action="store_true",
        help="No baja ningun reino: util para probar sin gastar cuota.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def es_montura(client: BlizzardClient, item_id: int, region: str) -> bool:
    """Si el objeto es una montura, que no van en la app."""
    try:
        respuesta = client._api_get(
            f"/data/wow/item/{item_id}", namespace=f"static-{region}"
        )
    except BlizzardError:
        return False
    if respuesta.status_code != 200:
        return False
    datos = respuesta.json()
    return (
        (datos.get("item_class") or {}).get("id") == CLASE_MISCELANEA
        and (datos.get("item_subclass") or {}).get("id") == SUBCLASE_MONTURA
    )


def construir_catalogo(client, client_es, config, reglas: dict) -> dict:
    """El catalogo de objetos, con nombre en espanol e icono."""
    objetos = []
    for item_id, regla in reglas.items():
        tabla = regla.max_price_by_ilvl or {}
        objetos.append({
            "id": item_id,
            "es": client_es.item_name(item_id) or regla.name,
            "en": regla.name,
            "icono": client.item_icon_url(item_id),
            "escala": bool(tabla),
            "ilvls": [
                {"ilvl": ilvl, "tope": tope} for ilvl, tope in sorted(tabla.items())
            ],
            "tope": regla.max_price,
        })
    objetos.sort(key=lambda o: o["es"])
    return {
        "version": CATALOGO_VERSION,
        "generado": int(datetime.now(timezone.utc).timestamp()),
        "orden": list(config.orden_personajes),
        "objetos": objetos,
    }


def recoger_precios(client, config, reglas, roster_path, state_dir) -> dict:
    """Baja los reinos donde vendes y se queda con el precio a batir."""
    roster = leer_rosters(roster_path)
    reino_por_personaje = {p.name: p.realm for p in roster}
    reinos = reinos_a_vigilar(reino_por_personaje, config.orden_personajes)
    if not reinos:
        log.warning(
            "Ninguno de los personajes de orden_personajes esta en %s: sin reinos "
            "que mirar.",
            roster_path,
        )
        return construir_precios({}, int(datetime.now(timezone.utc).timestamp()))

    log.info("Reinos donde vendes: %s", len(reinos))

    cache = RealmIdCache(Path(state_dir) / "realm_ids.json")
    ids_por_reino = resolve_connected_realms(client, cache, sorted(reinos), strict=False)
    cache.save()

    # Varios reinos comparten casa de subastas, asi que se baja una vez por
    # connected realm y se reparte a todos los suyos.
    reinos_por_id: dict[int, list[str]] = {}
    for nombre, realm_id in ids_por_reino.items():
        reinos_por_id.setdefault(realm_id, []).append(nombre)

    vigilados = set(reglas)
    por_reino: dict[str, tuple[dict, int]] = {}

    def una(realm_id: int):
        try:
            return realm_id, client.auctions(realm_id)
        except BlizzardError as exc:
            log.warning("Reino %s: %s", realm_id, exc)
            return realm_id, None

    with ThreadPoolExecutor(max_workers=config.settings.max_workers) as pool:
        for realm_id, snapshot in pool.map(una, reinos_por_id):
            if snapshot is None:
                # Sin dato es mejor que un dato viejo disfrazado de actual: el
                # reino simplemente no sale, y la app lo dice.
                continue
            minimos = minimos_del_reino(
                snapshot.auctions, vigilados, config.bonus_ilvl_map
            )
            visto = int(
                (snapshot.taken_at or datetime.now(timezone.utc)).timestamp()
            )
            for nombre in reinos_por_id[realm_id]:
                por_reino[slugify_realm(nombre)] = (minimos, visto)
            log.info(
                "  %s: %s producto(s) con precio", ", ".join(reinos_por_id[realm_id]),
                len(minimos),
            )

    return construir_precios(por_reino, int(datetime.now(timezone.utc).timestamp()))


def escribir(destino: Path, nombre: str, contenido: dict) -> bool:
    """Escribe el fichero. Devuelve True solo si ha cambiado algo.

    Comparar antes de escribir evita que el publicador genere un commit por hora
    con los mismos bytes cuando no se mueve nada.
    """
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / nombre
    texto = json.dumps(contenido, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    anterior = ruta.read_text(encoding="utf-8") if ruta.is_file() else None
    if anterior == texto:
        log.info("%s sin cambios.", nombre)
        return False
    ruta.write_text(texto, encoding="utf-8")
    log.info("%s escrito (%s KB).", nombre, len(texto) // 1024)
    return True


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    load_dotenv()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR

    def cliente(locale: str) -> BlizzardClient:
        return BlizzardClient(
            client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
            client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
            region=config.region,
            locale=locale,
            timeout=config.settings.request_timeout,
        )

    # La busqueda por nombre compara contra el nombre en el idioma del cliente,
    # y los del config estan en ingles: uno para buscar, otro para traducir.
    client = cliente(config.locale)
    client_es = cliente("es_ES")

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_items = ItemIdCache(state_dir / "item_ids.json")

    try:
        reglas = resolve_item_ids(client, config, cache_items)
    except ItemResolutionError as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR
    cache_items.save()

    # Las monturas fuera: en la app no aportan nada porque no las repartes entre
    # personajes, se venden donde caen.
    monturas = {i for i in reglas if es_montura(client, i, config.region)}
    if monturas:
        log.info("Monturas excluidas de la app: %s", len(monturas))
    reglas = {i: r for i, r in reglas.items() if i not in monturas}

    if not reglas:
        log.error("❌ No queda ningun objeto que publicar.")
        return EXIT_ERROR

    destino = Path(args.salida)
    cambios = escribir(
        destino, "catalogo.json", construir_catalogo(client, client_es, config, reglas)
    )

    if args.solo_catalogo:
        log.info("--solo-catalogo: no bajo ningun reino.")
    else:
        precios = recoger_precios(
            client, config, reglas, args.personajes, args.state_dir
        )
        cambios = escribir(destino, "precios.json", precios) or cambios

    log.info("✅ Listo%s.", "" if cambios else " (sin cambios)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
