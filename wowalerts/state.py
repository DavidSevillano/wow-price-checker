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
from typing import Iterable, Mapping

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


class NotifiedAuctions:
    """Subastas ya avisadas, con olvido automatico de las antiguas.

    Cada entrada guarda el numero de ejecucion en que se aviso. Las que llevan
    mas de `retention_runs` pasadas sin volver a verse se descartan, para que
    el fichero no crezca sin limite.
    """

    def __init__(self, path: str | Path, retention_runs: int = 72) -> None:
        self.path = Path(path)
        self.retention_runs = retention_runs
        data = _read_json(self.path) or {}
        raw = data.get("auctions")
        self._seen: dict[str, int] = (
            {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}
            if isinstance(raw, dict)
            else {}
        )
        self.run: int = int(data.get("run", 0)) + 1

    @staticmethod
    def key(realm_id: int, auction_id: int) -> str:
        """Los ids de subasta solo son unicos dentro de su reino."""
        return f"{realm_id}:{auction_id}"

    def is_new(self, realm_id: int, auction_id: int) -> bool:
        return self.key(realm_id, auction_id) not in self._seen

    def mark(self, realm_id: int, auction_id: int) -> None:
        self._seen[self.key(realm_id, auction_id)] = self.run

    def filter_new(self, deals: Iterable) -> list:
        """Devuelve solo los chollos que no se hayan avisado ya."""
        return [
            deal for deal in deals if self.is_new(deal.realm_id, deal.auction_id)
        ]

    def save(self) -> None:
        cutoff = self.run - self.retention_runs
        kept = {key: run for key, run in self._seen.items() if run > cutoff}
        dropped = len(self._seen) - len(kept)
        if dropped:
            log.debug("Olvidadas %s subastas antiguas del estado.", dropped)
        self._seen = kept
        _write_json_atomic(
            self.path,
            {"version": STATE_VERSION, "run": self.run, "auctions": kept},
        )

    def __len__(self) -> int:
        return len(self._seen)


class ItemIdCache:
    """Cache de 'nombre de objeto' -> 'id de objeto'.

    Los ids se resuelven en cada pasada, pero si la busqueda falla (un fallo
    puntual de la API) se recurre a lo guardado aqui en vez de dejar de vigilar
    ese objeto.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        data = _read_json(self.path) or {}
        raw = data.get("items")
        self._ids: dict[str, int] = (
            {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}
            if isinstance(raw, dict)
            else {}
        )

    def get(self, name: str) -> int | None:
        return self._ids.get(name)

    def set(self, name: str, item_id: int) -> None:
        self._ids[name] = item_id

    def update(self, mapping: Mapping[str, int]) -> None:
        self._ids.update(mapping)

    def save(self) -> None:
        _write_json_atomic(self.path, {"version": STATE_VERSION, "items": self._ids})
