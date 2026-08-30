"""Lectura de las subastas propias exportadas por el addon.

El addon guarda un JSON dentro de una cadena de Lua, asi que aqui no se
interpreta Lua: se extrae la cadena, se deshacen sus escapes y se parsea como
JSON. Es lo que hace que un cambio de formato de SavedVariables no rompa nada.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

PAYLOAD_RE = re.compile(r'\["payload"\]\s*=\s*"')

# WoW escapa asi los caracteres especiales dentro de una cadena guardada.
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


class MisSubastasError(Exception):
    """No se ha podido leer el volcado del addon."""


@dataclass(frozen=True)
class MyAuction:
    """Una subasta tuya, tal y como la vio el addon dentro del juego."""

    auction_id: int
    item_id: int
    item_name: str
    ilvl: int
    buyout_copper: int
    quantity: int
    character: str
    realm: str
    realm_slug: str
    # Los bonus ids identifican la version exacta del objeto (ilvl, calidad,
    # afijos). Dos subastas del mismo objeto con los mismos bonus ids son el
    # mismo producto; con distintos, no compiten entre si.
    bonus_ids: tuple[int, ...] = ()


def slugify_realm(name: str) -> str:
    """'Area 52' -> 'area-52', que es como los nombra la API de Blizzard.

    Los apostrofos se borran en vez de convertirse en guion, porque asi es como
    los trata Blizzard: "Zul'jin" es "zuljin", no "zul-jin".
    """
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(c)
    )
    sin_apostrofos = re.sub(r"['‘’]", "", sin_tildes)
    return re.sub(r"[^a-zA-Z0-9]+", "-", sin_apostrofos).strip("-").lower()


def extraer_payload(texto: str) -> str:
    """Saca la cadena JSON del fichero de SavedVariables."""
    match = PAYLOAD_RE.search(texto)
    if not match:
        raise MisSubastasError(
            "El volcado no contiene ningun campo 'payload'. Comprueba que el "
            "addon WowAlertsExport esta activado y que has abierto la Casa de "
            "Subastas al menos una vez."
        )

    salida: list[str] = []
    i = match.end()
    while i < len(texto):
        char = texto[i]
        if char == "\\":
            siguiente = texto[i + 1 : i + 2]
            if siguiente.isdigit():
                # WoW escribe los caracteres no imprimibles como \ddd decimal.
                digitos = ""
                for char_digito in texto[i + 1 : i + 4]:
                    if not char_digito.isdigit():
                        break
                    digitos += char_digito
                salida.append(chr(int(digitos)))
                i += 1 + len(digitos)
                continue
            salida.append(ESCAPES.get(siguiente, siguiente))
            i += 2
            continue
        if char == '"':
            return "".join(salida)
        salida.append(char)
        i += 1

    raise MisSubastasError("El volcado tiene una cadena sin cerrar; esta corrupto.")


def leer_payload(path: str | Path) -> dict:
    """Lee un fichero de SavedVariables y devuelve su payload ya parseado."""
    path = Path(path)
    try:
        texto = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MisSubastasError(f"No he podido leer {path}: {exc}") from exc

    try:
        datos = json.loads(extraer_payload(texto))
    except json.JSONDecodeError as exc:
        raise MisSubastasError(f"El payload de {path} no es JSON valido: {exc}") from exc

    if not isinstance(datos, dict):
        raise MisSubastasError(f"El payload de {path} no es un objeto JSON.")
    return datos


def fusionar_payloads(payloads: Iterable[Mapping]) -> dict[str, dict]:
    """Une varios volcados quedandose con el mas reciente de cada personaje.

    Hace falta porque puedes tener varias cuentas de WoW, cada una con su
    carpeta en WTF, y porque un mismo personaje aparece en todas las que hayan
    tenido su sesion abierta.
    """
    fusion: dict[str, dict] = {}
    for payload in payloads:
        personajes = payload.get("personajes")
        if not isinstance(personajes, dict):
            continue
        for clave, entrada in personajes.items():
            if not isinstance(entrada, dict):
                continue
            previo = fusion.get(clave)
            if previo is None or _exported_at(entrada) >= _exported_at(previo):
                fusion[clave] = entrada
    return fusion


def subastas_de_payloads(personajes: Mapping[str, Mapping]) -> list[MyAuction]:
    """Aplana los volcados fusionados en una lista de subastas."""
    subastas: list[MyAuction] = []
    for entrada in personajes.values():
        character = str(entrada.get("character") or "")
        realm = str(entrada.get("realm") or "")
        for cruda in entrada.get("auctions") or []:
            subasta = _to_auction(cruda, character, realm)
            if subasta is not None:
                subastas.append(subasta)
    subastas.sort(key=lambda s: (s.realm, s.character, s.auction_id))
    return subastas


def encontrar_savedvariables(wow_root: str | Path) -> list[Path]:
    """Todos los ficheros del addon, de todas tus cuentas de WoW."""
    patron = "WTF/Account/*/SavedVariables/WowAlertsExport.lua"
    return sorted(Path(wow_root).glob(patron))


def leer_de_wow(wow_root: str | Path) -> list[MyAuction]:
    """Lee y fusiona todo lo que haya exportado el addon."""
    ficheros = encontrar_savedvariables(wow_root)
    if not ficheros:
        raise MisSubastasError(
            f"No encuentro ningun WowAlertsExport.lua bajo {wow_root}.\n"
            "Comprueba la ruta de WoW y que has entrado al juego con el addon "
            "activado al menos una vez."
        )
    log.info("Leyendo %s volcado(s) del addon.", len(ficheros))
    return subastas_de_payloads(fusionar_payloads(leer_payload(f) for f in ficheros))


def escribir_snapshot(path: str | Path, subastas: Sequence[MyAuction]) -> bool:
    """Escribe mis_subastas.json. Devuelve True solo si el contenido ha cambiado.

    No lleva marcas de tiempo a proposito: asi dos volcados con las mismas
    subastas producen bytes identicos y el sincronizador no genera commits
    vacios cada cuarto de hora.
    """
    path = Path(path)
    contenido = json.dumps(
        {
            "version": SNAPSHOT_VERSION,
            "auctions": [_to_json(s) for s in subastas],
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    anterior = path.read_text(encoding="utf-8") if path.is_file() else None
    if anterior == contenido:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")
    return True


def leer_snapshot(path: str | Path) -> list[MyAuction]:
    """Lee mis_subastas.json. Un fichero que no existe son cero subastas."""
    path = Path(path)
    if not path.is_file():
        log.warning(
            "No existe %s: no se de ninguna subasta tuya. Ejecuta "
            "sync_subastas.py en tu PC para generarlo.",
            path,
        )
        return []

    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MisSubastasError(f"{path} no se puede leer: {exc}") from exc

    subastas: list[MyAuction] = []
    for cruda in datos.get("auctions") or []:
        subasta = _to_auction(cruda, cruda.get("character", ""), cruda.get("realm", ""))
        if subasta is not None:
            subastas.append(subasta)
    return subastas


def _exported_at(entrada: Mapping) -> int:
    valor = entrada.get("exportedAt")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else 0


def _to_auction(cruda: Any, character: str, realm: str) -> MyAuction | None:
    """Convierte una entrada cruda, o None si le falta algo imprescindible."""
    if not isinstance(cruda, Mapping):
        return None

    campos = {}
    for clave in ("auctionID", "itemID", "ilvl", "buyout"):
        valor = cruda.get(clave)
        if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
            log.debug("Subasta propia descartada, falta %s: %r", clave, cruda)
            return None
        campos[clave] = valor

    cantidad = cruda.get("quantity")
    bonus = cruda.get("bonusIDs")
    return MyAuction(
        bonus_ids=tuple(
            b for b in bonus if isinstance(b, int) and not isinstance(b, bool)
        )
        if isinstance(bonus, list)
        else (),
        auction_id=campos["auctionID"],
        item_id=campos["itemID"],
        item_name=str(cruda.get("itemName") or f"Objeto {campos['itemID']}"),
        ilvl=campos["ilvl"],
        buyout_copper=campos["buyout"],
        quantity=cantidad if isinstance(cantidad, int) and cantidad > 0 else 1,
        character=str(cruda.get("character") or character),
        realm=str(cruda.get("realm") or realm),
        realm_slug=slugify_realm(str(cruda.get("realm") or realm)),
    )


def _to_json(subasta: MyAuction) -> dict:
    return {
        "auctionID": subasta.auction_id,
        "itemID": subasta.item_id,
        "itemName": subasta.item_name,
        "ilvl": subasta.ilvl,
        "bonusIDs": list(subasta.bonus_ids),
        "buyout": subasta.buyout_copper,
        "quantity": subasta.quantity,
        "character": subasta.character,
        "realm": subasta.realm,
    }
