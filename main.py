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
from wowalerts.notifier import (
    DiscordError,
    DiscordNotifier,
    format_gold,
    realm_names_for,
)
from wowalerts.scanner import scan_realms
from wowalerts.state import ItemIconCache, ItemIdCache, NotifiedAuctions

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

    if args.realms:
        realm_ids = parse_realm_ids(args.realms)
        log.info("🎯 Escaneando %s reino(s) indicados a mano...", len(realm_ids))
    else:
        realm_ids = client.connected_realm_ids()
        log.info("🚀 Escaneando los %s reinos de %s...", len(realm_ids), config.region.upper())

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

    fresh = result.deals if args.ignore_state else notified.filter_new(result.deals)
    repeats = len(result.deals) - len(fresh)
    if repeats:
        log.info("🔁 %s chollo(s) ya avisados anteriormente, omitidos.", repeats)

    if fresh:
        realm_names = realm_names_for(fresh, client.connected_realm_name)
        log.info("🎉 %s chollo(s) nuevos:", len(fresh))
        print_deals(fresh, realm_names)

        if args.dry_run:
            log.info("🧪 --dry-run: no envio nada a Discord ni guardo el estado.")
        else:
            icon_urls = resolve_icons(client, icon_cache, fresh)
            icon_cache.save()
            messages = notifier.send_deals(
                fresh, realm_names, icon_urls, result.snapshot_at
            )
            log.info("📨 Enviado a Discord en %s mensaje(s).", messages)
            for deal in fresh:
                notified.mark(deal.realm_id, deal.auction_id)
    else:
        log.info("😴 Ningun chollo nuevo esta vez.")

    if not args.dry_run:
        notified.save()

    if result.failure_ratio > config.settings.failure_ratio_threshold:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        return run(args)
    except (ConfigError, BlizzardAuthError, DiscordError, ItemResolutionError) as exc:
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
