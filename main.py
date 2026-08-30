"""Vigilante de precios de la Casa de Subastas de WoW.

Escanea las subastas de todos los reinos de una region y avisa por Discord
cuando alguno de los objetos vigilados esta en compra directa por debajo del
precio que hayas fijado en config.yaml.

Uso tipico:

    py main.py --test-discord                  # comprobar el webhook
    py main.py --dry-run --realms 1305,1378    # prueba rapida, sin enviar nada
    py main.py                                 # escaneo completo real
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from wowalerts.config import ConfigError, load_config
from wowalerts.items import ItemResolutionError, resolve_item_ids
from wowalerts.misubastas import MisSubastasError, leer_snapshot
from wowalerts.notifier import (
    DiscordError,
    DiscordNotifier,
    format_gold,
    realm_names_for,
)
from wowalerts.realms import RealmResolutionError, resolve_connected_realms
from wowalerts.scanner import scan_realms
from wowalerts.snapshot import dump_is_stale, expected_dump_at
from wowalerts.state import (
    ItemIconCache,
    ItemIdCache,
    NotifiedAuctions,
    NotifiedUndercuts,
    RealmIdCache,
)
from wowalerts.undercut import find_undercuts

log = logging.getLogger("wowalerts")

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_TOO_MANY_FAILURES = 2

DEFAULT_STATE_DIR = Path(".state")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Avisa por Discord de chollos en la Casa de Subastas de WoW.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  py main.py --test-discord\n"
            "  py main.py --dry-run --realms 1305,1378 -v\n"
            "  py main.py\n"
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Ruta del fichero de configuracion (por defecto: config.yaml).",
    )
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help="Carpeta donde se guarda la memoria entre ejecuciones.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Escanea e imprime los chollos, pero no envia nada a Discord ni "
        "guarda el estado. Ideal para probar.",
    )
    parser.add_argument(
        "--realms",
        help="Lista de ids de reino separados por comas, para escanear solo "
        "esos en vez de toda la region. Acelera muchisimo las pruebas.",
    )
    parser.add_argument(
        "--test-discord",
        action="store_true",
        help="Envia un mensaje de prueba al webhook y termina.",
    )
    parser.add_argument(
        "--ignore-state",
        action="store_true",
        help="Avisa tambien de chollos ya notificados en pasadas anteriores.",
    )
    parser.add_argument(
        "--undercut",
        action="store_true",
        help="En vez de buscar chollos, avisa si alguien ha adelantado a tus "
        "propias subastas de los objetos vigilados. Necesita mis_subastas.json, "
        "que genera sync_subastas.py en tu PC.",
    )
    parser.add_argument(
        "--mis-subastas",
        default="mis_subastas.json",
        help="Ruta del volcado de tus subastas (por defecto: mis_subastas.json).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra el detalle de cada subasta vista (util para revisar los "
        "bonus ids cuando algo no cuadra).",
    )
    return parser


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )


def parse_realm_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            raise ConfigError(
                f"--realms solo admite numeros separados por comas; "
                f"{chunk!r} no lo es."
            )
        ids.append(int(chunk))
    if not ids:
        raise ConfigError("--realms no contiene ningun id de reino.")
    return sorted(set(ids))


def print_deals(deals, realm_names) -> None:
    """Vuelca los chollos por consola (lo que se enviaria a Discord)."""
    for deal in deals:
        ilvl = f"ilvl {deal.ilvl}" if deal.ilvl_confirmed else "ilvl SIN CONFIRMAR"
        realm = realm_names.get(deal.realm_id, f"Reino {deal.realm_id}")
        log.info(
            "  %s | %s g (%s, limite %s g, -%.0f%%) | %s",
            deal.item_name,
            format_gold(deal.price_gold),
            ilvl,
            format_gold(deal.threshold_gold),
            deal.discount_pct,
            realm,
        )


def resolve_icons(client, cache, deals) -> dict[int, str]:
    """Miniatura de cada objeto con chollo, pidiendola solo la primera vez.

    Los iconos no cambian, asi que se cachean. Un fallo aqui no impide el aviso:
    simplemente sale sin miniatura.
    """
    urls: dict[int, str] = {}
    for item_id in dict.fromkeys(deal.item_id for deal in deals):
        url = cache.get(item_id) or client.item_icon_url(item_id)
        if url:
            urls[item_id] = url
            cache.set(item_id, url)
    return urls


def agrupar_por_reino(mis_subastas, realm_ids_por_slug) -> dict[int, list]:
    """Agrupa tus subastas por connected realm.

    Varios reinos comparten connected realm, asi que agrupar por ahi y no por
    nombre evita descargar dos veces el mismo volcado.
    """
    grupos: dict[int, list] = {}
    for subasta in mis_subastas:
        realm_id = realm_ids_por_slug.get(subasta.realm_slug)
        if realm_id is None:
            log.warning(
                "Omito las subastas de %s: no se a que reino conectado pertenece.",
                subasta.realm,
            )
            continue
        grupos.setdefault(realm_id, []).append(subasta)
    return grupos


def run_undercut(
    client,
    config,
    rules_by_item_id,
    notifier,
    state_dir: Path,
    mis_subastas_path: str,
    *,
    dry_run: bool,
    ignore_state: bool,
) -> int:
    """Una pasada de vigilancia sobre tus propias subastas."""
    todas = leer_snapshot(mis_subastas_path)
    # Solo interesan los objetos que vigila config.yaml: el resto de lo que
    # tengas puesto (monturas, mochilas, decoracion) no es el negocio.
    mis_subastas = [s for s in todas if s.item_id in rules_by_item_id]

    if not mis_subastas:
        log.info(
            "😴 De tus %s subasta(s) conocidas, ninguna es de un objeto vigilado. "
            "Nada que comprobar.",
            len(todas),
        )
        return EXIT_OK

    log.info(
        "📋 %s de tus %s subastas son de objetos vigilados, en %s reino(s).",
        len(mis_subastas),
        len(todas),
        len({s.realm_slug for s in mis_subastas}),
    )

    realm_cache = RealmIdCache(state_dir / "realm_ids.json")
    realm_ids_por_slug = resolve_connected_realms(
        client, realm_cache, (s.realm_slug for s in mis_subastas), strict=False
    )
    if not dry_run:
        realm_cache.save()

    grupos = agrupar_por_reino(mis_subastas, realm_ids_por_slug)
    if not grupos:
        raise RealmResolutionError(
            "No he podido resolver ninguno de tus reinos. Sin eso no puedo "
            "descargar sus subastas."
        )

    notified = NotifiedUndercuts(
        state_dir / "undercuts.json", config.settings.state_retention_runs
    )
    icon_cache = ItemIconCache(state_dir / "item_icons.json")

    todos: list = []
    snapshot_at = None
    for realm_id, mias in grupos.items():
        try:
            snapshot = client.auctions(realm_id)
        except BlizzardError as exc:
            log.warning("Reino %s: %s", realm_id, exc)
            continue
        if snapshot.taken_at and (snapshot_at is None or snapshot.taken_at > snapshot_at):
            snapshot_at = snapshot.taken_at
        todos.extend(
            find_undercuts(snapshot.auctions, mias, config.bonus_ilvl_map, realm_id)
        )

    frescos = todos if ignore_state else notified.filter_new(todos)
    repetidos = len(todos) - len(frescos)
    if repetidos:
        log.info("🔁 %s undercut(s) ya avisados, omitidos.", repetidos)

    if not frescos:
        log.info("😌 Nadie nuevo te ha adelantado.")
        if not dry_run:
            notified.save()
        return EXIT_OK

    log.info("⚔️ Te han adelantado en %s subasta(s):", len(frescos))
    for undercut in frescos:
        log.info(
            "  %s | tuya %s g vs %s g | ilvl %s | %s en %s",
            undercut.mine.item_name,
            format_gold(undercut.my_price_gold),
            format_gold(undercut.rival_price_gold),
            undercut.mine.ilvl,
            undercut.mine.character,
            undercut.mine.realm,
        )

    if dry_run:
        log.info("🧪 --dry-run: no envio nada a Discord ni guardo el estado.")
        return EXIT_OK

    realm_names = {
        realm_id: client.connected_realm_name(realm_id) for realm_id in grupos
    }

    icon_urls: dict[int, str] = {}
    for item_id in dict.fromkeys(u.mine.item_id for u in frescos):
        url = icon_cache.get(item_id) or client.item_icon_url(item_id)
        if url:
            icon_urls[item_id] = url
            icon_cache.set(item_id, url)
    icon_cache.save()

    enviados = notifier.send_undercuts(frescos, realm_names, icon_urls, snapshot_at)
    log.info("📨 Enviados a Discord %s aviso(s).", len(enviados))

    # Solo se marcan los que han salido de verdad, igual que con los chollos.
    for undercut in enviados:
        notified.mark(
            notified.key(
                undercut.realm_id, undercut.mine.auction_id, undercut.rival_auction_id
            )
        )
    notified.save()
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    load_dotenv()

    config = load_config(args.config)

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    notifier = DiscordNotifier(webhook_url) if webhook_url else None

    if args.test_discord:
        if notifier is None:
            raise DiscordError(
                "Falta DISCORD_WEBHOOK_URL, asi que no hay nada que probar.\n"
                "Copia .env.example a .env y rellenalo."
            )
        notifier.send_test()
        log.info("✅ Mensaje de prueba enviado. Miralo en Discord.")
        return EXIT_OK

    if notifier is None and not args.dry_run:
        raise DiscordError(
            "Falta DISCORD_WEBHOOK_URL. Copia .env.example a .env y rellenalo, "
            "o usa --dry-run si solo quieres ver los resultados por consola."
        )

    client = BlizzardClient(
        client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
        client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )

    state_dir = Path(args.state_dir)
    item_cache = ItemIdCache(state_dir / "item_ids.json")
    icon_cache = ItemIconCache(state_dir / "item_icons.json")
    notified = NotifiedAuctions(
        state_dir / "notified.json", config.settings.state_retention_runs
    )

    log.info("🔍 Identificando los %s objetos vigilados...", len(config.items))
    rules_by_item_id = resolve_item_ids(client, config, item_cache)
    if not args.dry_run:
        item_cache.save()

    if args.undercut:
        return run_undercut(
            client,
            config,
            rules_by_item_id,
            notifier,
            state_dir,
            args.mis_subastas,
            dry_run=args.dry_run,
            ignore_state=args.ignore_state,
        )

    if args.realms:
        realm_ids = parse_realm_ids(args.realms)
        log.info("🎯 Escaneando %s reino(s) indicados a mano...", len(realm_ids))
    else:
        realm_ids = client.connected_realm_ids()
        log.info("🚀 Escaneando los %s reinos de %s...", len(realm_ids), config.region.upper())

    settings = config.settings
    intentos = settings.stale_retries

    while True:
        result = scan_once(
            client,
            config,
            realm_ids,
            rules_by_item_id,
            notified,
            icon_cache,
            notifier,
            dry_run=args.dry_run,
            ignore_state=args.ignore_state,
        )

        ahora = datetime.now(timezone.utc)
        if not dump_is_stale(result.snapshot_at, ahora, settings.dump_minute):
            break

        toca = expected_dump_at(ahora, settings.dump_minute).strftime("%H:%M")
        if intentos < 1:
            log.warning(
                "⚠️  El volcado de las %s UTC sigue sin aparecer y ya no quedan "
                "reintentos. Lo recogera la pasada de la hora siguiente.",
                toca,
            )
            break

        log.warning(
            "⏳ Blizzard aun no ha publicado el volcado de las %s UTC: lo leido "
            "es de la hora anterior. Espero %s s y vuelvo a mirar (quedan %s "
            "intento(s)).",
            toca,
            settings.stale_retry_wait_seconds,
            intentos,
        )
        intentos -= 1
        time.sleep(settings.stale_retry_wait_seconds)

    if result.failure_ratio > settings.failure_ratio_threshold:
        message = (
            f"Han fallado {len(result.realms_failed)} de {result.realms_total} reinos "
            f"en esta pasada. Los resultados estan incompletos: puede haber chollos "
            f"que no hayas visto."
        )
        log.error("❌ %s", message)
        if notifier and not args.dry_run:
            try:
                notifier.send_warning("Escaneo incompleto", message)
            except DiscordError as exc:
                log.error("Ademas, no he podido avisar por Discord: %s", exc)
        return EXIT_TOO_MANY_FAILURES

    return EXIT_OK


def scan_once(
    client,
    config,
    realm_ids,
    rules_by_item_id,
    notified,
    icon_cache,
    notifier,
    *,
    dry_run: bool,
    ignore_state: bool,
):
    """Una lectura completa de la region, con sus avisos ya enviados.

    Se ejecuta mas de una vez cuando el volcado de Blizzard llega tarde. Cada
    intento avisa por su cuenta y marca lo enviado, de modo que un chollo visto
    solo en el primer intento no se pierde aunque en el segundo ya no aparezca:
    para entonces lo habran comprado, pero el aviso salio a tiempo.
    """
    started = time.monotonic()
    result = scan_realms(client, config, realm_ids, rules_by_item_id)
    elapsed = time.monotonic() - started

    log.info(
        "📊 %s/%s reinos leidos en %.0f s (%s subastas analizadas).",
        result.realms_ok,
        result.realms_total,
        elapsed,
        f"{result.auctions_seen:,}".replace(",", "."),
    )
    if result.snapshot_at:
        edad = (
            datetime.now(timezone.utc) - result.snapshot_at
        ).total_seconds() / 60
        log.info(
            "🕒 Datos del volcado de las %s UTC (hace %.0f min). Blizzard lo "
            "regenera cada hora: si esa cifra se acerca a 60, el cron se ha "
            "desalineado y conviene retrasarlo.",
            result.snapshot_at.strftime("%H:%M"),
            edad,
        )

    if result.realms_failed:
        log.warning(
            "⚠️  %s reino(s) han fallado: %s",
            len(result.realms_failed),
            ", ".join(str(r) for r in sorted(result.realms_failed)[:20]),
        )

    fresh = result.deals if ignore_state else notified.filter_new(result.deals)
    repeats = len(result.deals) - len(fresh)
    if repeats:
        log.info("🔁 %s chollo(s) ya avisados anteriormente, omitidos.", repeats)

    if fresh:
        realm_names = realm_names_for(fresh, client.connected_realm_name)
        log.info("🎉 %s chollo(s) nuevos:", len(fresh))
        print_deals(fresh, realm_names)

        if dry_run:
            log.info("🧪 --dry-run: no envio nada a Discord ni guardo el estado.")
        else:
            icon_urls = resolve_icons(client, icon_cache, fresh)
            icon_cache.save()
            sent = notifier.send_deals(
                fresh, realm_names, icon_urls, result.snapshot_at
            )
            log.info("📨 Enviados a Discord %s chollo(s).", len(sent))

            # Solo se marcan los que han salido de verdad. Si algo no cupo en
            # el aviso, sigue sin marcar y la proxima pasada lo enviara.
            for deal in sent:
                notified.mark(deal.realm_id, deal.auction_id)

            pendientes = len(fresh) - len(sent)
            if pendientes:
                log.warning(
                    "⏭️  %s chollo(s) no caben en este aviso; se enviaran en la "
                    "proxima pasada.",
                    pendientes,
                )
    else:
        log.info("😴 Ningun chollo nuevo esta vez.")

    if not dry_run:
        # Se guarda en cada intento, no al final: si la pasada muriera durante
        # la espera, lo ya avisado seguiria constando y no se repetiria.
        notified.save()

    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        return run(args)
    except (
        ConfigError,
        BlizzardAuthError,
        DiscordError,
        ItemResolutionError,
        MisSubastasError,
        RealmResolutionError,
    ) as exc:
        log.error("❌ %s", exc)
        return EXIT_CONFIG_ERROR
    except BlizzardError as exc:
        log.error("❌ Error hablando con la API de Blizzard: %s", exc)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario.")
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
