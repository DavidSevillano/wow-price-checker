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
                  vendes (`reinos`) y en todos los de la region (`mercado`, el
                  buscador de la app). Es el dato que no sobrevive a la pasada:
                  el volcado de un reino son decenas de miles de subastas que se
                  miran y se tiran.

Va aparte de main.py a proposito. main.py es el que te manda las alertas y no
conviene tocarlo para esto.
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
from wowalerts.precios import (
    construir_mercado,
    construir_precios,
    minimos_del_reino,
    reinos_a_vigilar,
)
from wowalerts.realms import resolve_connected_realms
from wowalerts.state import ItemIdCache, JsonMapCache, RealmIdCache

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


def fichas_de_grupos(client, realm_ids, state_dir) -> dict[int, tuple[str, list[str]]]:
    """Nombre y slugs de cada connected realm, cacheados entre pasadas.

    Un grupo no cambia de reinos casi nunca, y sin cache serian 92 peticiones
    mas cada hora para volver a oir lo mismo.
    """
    cache = JsonMapCache(Path(state_dir) / "grupos_reinos.json", "grupos")
    fichas: dict[int, tuple[str, list[str]]] = {}
    for realm_id in realm_ids:
        guardada = cache.get(realm_id)
        if isinstance(guardada, dict) and guardada.get("nombre"):
            fichas[realm_id] = (guardada["nombre"], list(guardada.get("slugs") or []))
            continue
        ficha = client.connected_realm_ficha(realm_id)
        if ficha is None:
            # Sin cachear: el nombre de relleno no debe sobrevivir a la pasada.
            fichas[realm_id] = (f"Reino {realm_id}", [])
            continue
        cache.set(realm_id, {"nombre": ficha[0], "slugs": ficha[1]})
        fichas[realm_id] = ficha
    cache.save()
    return fichas


def recoger_precios(client, config, reglas, roster_path, state_dir) -> dict:
    """Baja toda la region y se queda con el precio mas barato de cada reino.

    Dos usos del mismo volcado: el precio a batir en los reinos donde vendes
    (`reinos`) y el buscador de la app, que dice donde esta mas barato cada
    objeto en toda la region (`mercado`).
    """
    roster = leer_rosters(roster_path)
    reino_por_personaje = {p.name: p.realm for p in roster}
    reinos = reinos_a_vigilar(reino_por_personaje, config.orden_personajes)
    if not reinos:
        log.warning(
            "Ninguno de los personajes de orden_personajes esta en %s: sin reinos "
            "donde vendes.",
            roster_path,
        )
    log.info("Reinos donde vendes: %s", len(reinos))

    cache = RealmIdCache(Path(state_dir) / "realm_ids.json")
    ids_por_reino = resolve_connected_realms(client, cache, sorted(reinos), strict=False)
    cache.save()

    # Varios reinos comparten casa de subastas, asi que se baja una vez por
    # connected realm y se reparte a todos los suyos.
    reinos_por_id: dict[int, list[str]] = {}
    for nombre, realm_id in ids_por_reino.items():
        reinos_por_id.setdefault(realm_id, []).append(nombre)

    try:
        region = set(client.connected_realm_ids())
    except BlizzardError as exc:
        # El buscador se queda con tus reinos; lo de siempre sigue saliendo.
        log.warning("No he podido listar los reinos de la region: %s", exc)
        region = set()
    todos = sorted(region | set(reinos_por_id))
    log.info("Reinos de la region a bajar: %s", len(todos))
    fichas = fichas_de_grupos(client, todos, state_dir)

    vigilados = set(reglas)
    por_reino: dict[str, tuple[dict, int]] = {}
    grupos: list[tuple[str, list[str], dict, int]] = []

    def una(realm_id: int):
        try:
            return realm_id, client.auctions(realm_id)
        except BlizzardError as exc:
            log.warning("Reino %s: %s", realm_id, exc)
            return realm_id, None

    with ThreadPoolExecutor(max_workers=config.settings.max_workers) as pool:
        for realm_id, snapshot in pool.map(una, todos):
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
            nombre, slugs = fichas[realm_id]
            grupos.append((nombre, slugs, minimos, visto))
            for mio in reinos_por_id.get(realm_id, []):
                por_reino[slugify_realm(mio)] = (minimos, visto)
            log.debug("  %s: %s producto(s) con precio", nombre, len(minimos))

    log.info("Reinos con dato: %s de %s", len(grupos), len(todos))
    return construir_precios(
        por_reino,
        int(datetime.now(timezone.utc).timestamp()),
        mercado=construir_mercado(grupos),
    )


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
