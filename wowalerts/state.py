"""Memoria entre ejecuciones.

Sin esto, como una subasta dura horas y el escaneo corre cada hora, el mismo
chollo se avisaria una y otra vez. Aqui se guarda que subastas ya se han
notificado y los ids de objeto ya resueltos.

Los ficheros se escriben de forma atomica (fichero temporal + rename) para que
una interrupcion a mitad no deje un JSON corrupto.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

log = logging.getLogger(__name__)

STATE_VERSION = 1


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s ilegible (%s); empiezo de cero.", path, exc)
        return None
    return data if isinstance(data, dict) else None


class NotifiedKeys:
    """Claves ya avisadas, con olvido automatico de las antiguas.

    Cada entrada guarda el numero de ejecucion en que se aviso. Las que llevan
    mas de `retention_runs` pasadas sin volver a verse se descartan, para que
    el fichero no crezca sin limite.
    """

    #: Clave del JSON bajo la que vive esta memoria. Dos memorias con secciones
    #: distintas pueden compartir fichero sin pisarse.
    section = "auctions"

    def __init__(self, path: str | Path, retention_runs: int = 72) -> None:
        self.path = Path(path)
        self.retention_runs = retention_runs
        data = _read_json(self.path) or {}
        raw = data.get(self.section)
        self._seen: dict[str, int] = (
            {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}
            if isinstance(raw, dict)
            else {}
        )
        self.run: int = int(data.get("run", 0)) + 1

    def is_new(self, *key_parts: Any) -> bool:
        return self._as_key(key_parts) not in self._seen

    def mark(self, *key_parts: Any) -> None:
        self._seen[self._as_key(key_parts)] = self.run

    def save(self) -> None:
        cutoff = self.run - self.retention_runs
        kept = {key: run for key, run in self._seen.items() if run > cutoff}
        dropped = len(self._seen) - len(kept)
        if dropped:
            log.debug("Olvidadas %s entradas antiguas del estado.", dropped)
        self._seen = kept
        _write_json_atomic(
            self.path,
            {"version": STATE_VERSION, "run": self.run, self.section: kept},
        )

    def __len__(self) -> int:
        return len(self._seen)

    @staticmethod
    def _as_key(parts: tuple) -> str:
        """Acepta tanto una clave ya montada como sus trozos sueltos."""
        if len(parts) == 1:
            return str(parts[0])
        return ":".join(str(p) for p in parts)


class NotifiedAuctions(NotifiedKeys):
    """Subastas ya avisadas en el escaneo de chollos."""

    section = "auctions"

    @staticmethod
    def key(realm_id: int, auction_id: int) -> str:
        """Los ids de subasta solo son unicos dentro de su reino."""
        return f"{realm_id}:{auction_id}"

    def filter_new(self, deals: Iterable) -> list:
        """Devuelve solo los chollos que no se hayan avisado ya."""
        return [
            deal
            for deal in deals
            if self.is_new(self.key(deal.realm_id, deal.auction_id))
        ]


class NotifiedUndercuts(NotifiedKeys):
    """Parejas 'subasta tuya / subasta rival' ya avisadas.

    La clave lleva las dos subastas a proposito: si reposteas, tu id cambia y
    la pareja es nueva, asi que si ese rival te sigue adelantando te enteras.
    """

    section = "undercuts"

    @staticmethod
    def key(realm_id: int, my_auction_id: int, rival_auction_id: int) -> str:
        return f"{realm_id}:{my_auction_id}:{rival_auction_id}"

    def filter_new(self, undercuts: Iterable) -> list:
        """Devuelve solo los undercuts que no se hayan avisado ya."""
        return [
            u
            for u in undercuts
            if self.is_new(self.key(u.realm_id, u.mine.auction_id, u.rival_auction_id))
        ]


class JsonMapCache:
    """Diccionario sencillo persistido en disco.

    Sirve de red de seguridad: si una consulta a la API falla puntualmente, se
    usa lo que se guardo en la pasada anterior en vez de perder el dato.
    """

    def __init__(self, path: str | Path, section: str = "items") -> None:
        self.path = Path(path)
        self.section = section
        raw = (_read_json(self.path) or {}).get(section)
        self._data: dict[str, Any] = (
            {str(k): v for k, v in raw.items()} if isinstance(raw, dict) else {}
        )

    def get(self, key: Any) -> Any | None:
        return self._data.get(str(key))

    def set(self, key: Any, value: Any) -> None:
        self._data[str(key)] = value

    def update(self, mapping: Mapping[Any, Any]) -> None:
        for key, value in mapping.items():
            self.set(key, value)

    def save(self) -> None:
        _write_json_atomic(
            self.path, {"version": STATE_VERSION, self.section: self._data}
        )

    def __len__(self) -> int:
        return len(self._data)


class ItemIdCache(JsonMapCache):
    """Cache de 'nombre de objeto' -> 'id de objeto'."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "items")


class ItemIconCache(JsonMapCache):
    """Cache de 'id de objeto' -> 'url del icono'.

    Los iconos no cambian casi nunca, asi que se piden una sola vez y se
    reutilizan en todas las pasadas siguientes.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "icons")


class RealmIdCache(JsonMapCache):
    """Cache de 'slug de reino' -> 'id de connected realm'.

    Un reino no cambia de connected realm salvo fusion, que es un evento raro
    y anunciado, asi que se pide una vez y se reutiliza siempre.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "realms")
