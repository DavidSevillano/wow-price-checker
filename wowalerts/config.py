"""Carga y validacion de config.yaml.

La configuracion es lo unico que se edita a mano, asi que cualquier error se
detecta aqui y se explica en castellano, antes de gastar una sola peticion a
la API de Blizzard.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

VALID_REGIONS = ("eu", "us", "kr", "tw")
COPPER_PER_GOLD = 10_000


class ConfigError(Exception):
    """La configuracion es invalida. El mensaje explica que hay que arreglar."""


@dataclass(frozen=True)
class ItemRule:
    """Un objeto vigilado y sus precios maximos por ilvl."""

    name: str
    max_price_by_ilvl: Mapping[int, int]  # ilvl -> precio maximo en oro
    item_id: int | None = None

    def threshold_gold(self, ilvl: int) -> int | None:
        """Precio maximo para ese ilvl, o None si ese ilvl no interesa."""
        return self.max_price_by_ilvl.get(ilvl)

    @property
    def cheapest_threshold_gold(self) -> int:
        """Umbral mas bajo del objeto.

        Se usa cuando no se ha podido determinar el ilvl: solo se avisa si el
        precio esta por debajo incluso del ilvl mas barato, para no inundar de
        falsas alarmas.
        """
        return min(self.max_price_by_ilvl.values())


@dataclass(frozen=True)
class Settings:
    alert_on_unconfirmed_ilvl: bool = True
    # Ojo al subirlo: cada reino en vuelo mantiene en memoria su lista de
    # subastas ya parseada, que en un reino grande son cientos de MB.
    max_workers: int = 8
    request_timeout: int = 45
    state_retention_runs: int = 72
    failure_ratio_threshold: float = 0.30
    # Minuto en el que Blizzard publica el volcado de subastas. Si alguna vez
    # lo mueve, el log de cada pasada canta la antiguedad y basta cambiarlo aqui.
    dump_minute: int = 31
    # Si al escanear resulta que el volcado de esta hora todavia no ha salido,
    # se espera y se vuelve a mirar, en vez de perder la hora entera. A 0 se
    # desactiva y la pasada se conforma con lo que haya.
    stale_retries: int = 2
    stale_retry_wait_seconds: int = 120
    # ------------------------------------------------------------------------
    #  Ventas de tus propias subastas
    # ------------------------------------------------------------------------
    # Comision que se queda la casa de subastas al vender, en porcentaje. Es lo
    # que separa el precio al que publicas de lo que llega al buzon.
    ah_cut_pct: int = 5
    # Duracion MAS CORTA con la que publicas, en horas. Va la mas corta y no la
    # habitual porque de aqui sale una cota: con una duracion mayor que la real
    # se afirmarian ventas que en realidad son caducaciones.
    listing_hours: int = 12


@dataclass(frozen=True)
class Config:
    region: str
    items: tuple[ItemRule, ...]
    bonus_ilvl_map: Mapping[int, int]
    settings: Settings

    @property
    def locale(self) -> str:
        return "en_GB" if self.region in ("eu", "kr", "tw") else "en_US"


def load_config(path: str | Path) -> Config:
    """Lee y valida config.yaml. Lanza ConfigError con un mensaje util."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(
            f"No encuentro el fichero de configuracion: {path}\n"
            "Copia el config.yaml de ejemplo del repositorio."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} no es YAML valido:\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} deberia contener un mapa de opciones en la raiz.")

    return Config(
        region=_parse_region(raw.get("region", "eu")),
        items=_parse_items(raw.get("items")),
        bonus_ilvl_map=_parse_bonus_map(raw.get("bonus_ilvl_map") or {}),
        settings=_parse_settings(raw.get("settings") or {}),
    )


def _parse_region(value: Any) -> str:
    region = str(value).strip().lower()
    if region not in VALID_REGIONS:
        raise ConfigError(
            f"'region' vale {value!r} y solo admite: {', '.join(VALID_REGIONS)}."
        )
    return region


def _parse_items(value: Any) -> tuple[ItemRule, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("'items' debe ser una lista con al menos un objeto.")

    rules: list[ItemRule] = []
    seen: set[str] = set()

    for index, entry in enumerate(value, start=1):
        where = f"items[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(
                f"{where} deberia ser un mapa con 'name' y 'max_price_by_ilvl'."
            )

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: falta 'name' o esta vacio.")
        name = name.strip()

        if name in seen:
            raise ConfigError(f"{where}: el objeto {name!r} esta repetido en la lista.")
        seen.add(name)

        rules.append(
            ItemRule(
                name=name,
                max_price_by_ilvl=_parse_price_table(
                    entry.get("max_price_by_ilvl"), name
                ),
                item_id=_parse_optional_item_id(entry.get("item_id"), name),
            )
        )

    return tuple(rules)


def _parse_price_table(value: Any, item_name: str) -> Mapping[int, int]:
    if not isinstance(value, dict) or not value:
        raise ConfigError(
            f"{item_name!r}: 'max_price_by_ilvl' debe tener al menos un par "
            "ilvl: precio. Ejemplo -> max_price_by_ilvl: { 311: 90000 }"
        )

    table: dict[int, int] = {}
    for ilvl, price in value.items():
        if isinstance(ilvl, bool) or isinstance(price, bool):
            raise ConfigError(
                f"{item_name!r}: en 'max_price_by_ilvl' hay un valor booleano; "
                "tanto el ilvl como el precio deben ser numeros enteros."
            )
        try:
            ilvl_int = int(ilvl)
            price_int = int(price)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"{item_name!r}: en 'max_price_by_ilvl' tanto el ilvl como el precio "
                f"deben ser numeros enteros (he encontrado {ilvl!r}: {price!r})."
            ) from exc

        if ilvl_int <= 0:
            raise ConfigError(f"{item_name!r}: el ilvl {ilvl_int} no es valido.")
        if price_int <= 0:
            raise ConfigError(
                f"{item_name!r}: el precio para ilvl {ilvl_int} es {price_int}; "
                "debe ser mayor que 0 (se expresa en oro, no en cobre)."
            )
        table[ilvl_int] = price_int

    return table


def _parse_optional_item_id(value: Any, item_name: str) -> int | None:
    if value is None:
        return None
    try:
        item_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{item_name!r}: 'item_id' debe ser un numero entero.") from exc
    if item_id <= 0:
        raise ConfigError(f"{item_name!r}: 'item_id' debe ser mayor que 0.")
    return item_id


def _parse_bonus_map(value: Any) -> Mapping[int, int]:
    if not isinstance(value, dict):
        raise ConfigError("'bonus_ilvl_map' debe ser un mapa de 'bonus id: ilvl'.")

    mapping: dict[int, int] = {}
    for bonus_id, ilvl in value.items():
        try:
            mapping[int(bonus_id)] = int(ilvl)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                "'bonus_ilvl_map': tanto el bonus id como el ilvl deben ser enteros "
                f"(he encontrado {bonus_id!r}: {ilvl!r})."
            ) from exc
    return mapping


def _parse_settings(value: Any) -> Settings:
    if not isinstance(value, dict):
        raise ConfigError("'settings' debe ser un mapa de opciones.")

    defaults = Settings()
    unknown = set(value) - set(defaults.__dataclass_fields__)
    if unknown:
        raise ConfigError(
            f"'settings' tiene opciones que no reconozco: {', '.join(sorted(unknown))}.\n"
            f"Las validas son: {', '.join(sorted(defaults.__dataclass_fields__))}."
        )

    try:
        settings = Settings(
            alert_on_unconfirmed_ilvl=bool(
                value.get(
                    "alert_on_unconfirmed_ilvl", defaults.alert_on_unconfirmed_ilvl
                )
            ),
            max_workers=int(value.get("max_workers", defaults.max_workers)),
            request_timeout=int(value.get("request_timeout", defaults.request_timeout)),
            state_retention_runs=int(
                value.get("state_retention_runs", defaults.state_retention_runs)
            ),
            failure_ratio_threshold=float(
                value.get("failure_ratio_threshold", defaults.failure_ratio_threshold)
            ),
            dump_minute=int(value.get("dump_minute", defaults.dump_minute)),
            stale_retries=int(value.get("stale_retries", defaults.stale_retries)),
            stale_retry_wait_seconds=int(
                value.get(
                    "stale_retry_wait_seconds", defaults.stale_retry_wait_seconds
                )
            ),
            ah_cut_pct=int(value.get("ah_cut_pct", defaults.ah_cut_pct)),
            listing_hours=int(value.get("listing_hours", defaults.listing_hours)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'settings' tiene un valor con formato incorrecto: {exc}") from exc

    if settings.max_workers < 1:
        raise ConfigError("'max_workers' debe ser al menos 1.")
    if settings.request_timeout < 1:
        raise ConfigError("'request_timeout' debe ser al menos 1 segundo.")
    if settings.state_retention_runs < 1:
        raise ConfigError("'state_retention_runs' debe ser al menos 1.")
    if not 0.0 < settings.failure_ratio_threshold <= 1.0:
        raise ConfigError("'failure_ratio_threshold' debe estar entre 0 (excluido) y 1.")
    if not 0 <= settings.dump_minute <= 59:
        raise ConfigError("'dump_minute' es un minuto del reloj: entre 0 y 59.")
    if settings.stale_retries < 0:
        raise ConfigError("'stale_retries' no puede ser negativo (0 lo desactiva).")
    if not 0 <= settings.ah_cut_pct < 100:
        raise ConfigError(
            "'ah_cut_pct' es el porcentaje que se queda la casa de subastas: "
            "entre 0 y 99."
        )
    if not 1 <= settings.listing_hours <= 48:
        raise ConfigError(
            "'listing_hours' son las horas de tus publicaciones: entre 1 y 48. "
            "Pon la duracion MAS CORTA que uses, no la habitual."
        )
    if settings.stale_retry_wait_seconds < 1:
        raise ConfigError("'stale_retry_wait_seconds' debe ser al menos 1 segundo.")

    return settings
