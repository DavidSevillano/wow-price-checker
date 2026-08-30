"""Traduccion de nombres de reino a ids de connected realm.

Las subastas tuyas llegan con el nombre del reino tal y como se ve en el juego,
y la API las sirve por connected realm. Este modulo hace el puente, cacheando
el resultado porque un reino no cambia de grupo casi nunca.
"""

from __future__ import annotations

import logging
from typing import Iterable

from .blizzard import BlizzardError
from .misubastas import slugify_realm

log = logging.getLogger(__name__)


class RealmResolutionError(Exception):
    """No se ha podido averiguar a que connected realm pertenece un reino."""


def resolve_connected_realms(
    client,
    cache,
    realm_slugs: Iterable[str],
    strict: bool = True,
) -> dict[str, int]:
    """Devuelve {slug: connected realm id} para los reinos indicados.

    Con `strict=False` los reinos que fallen se omiten con un aviso en el log,
    en vez de tumbar la pasada entera: mas vale vigilar cinco reinos de seis que
    ninguno.
    """
    resultado: dict[str, int] = {}
    indice: list[dict] | None = None

    for slug in dict.fromkeys(realm_slugs):
        cacheado = cache.get(slug)
        if isinstance(cacheado, int):
            resultado[slug] = cacheado
            continue

        try:
            realm_id = client.connected_realm_id_for(slug)
        except BlizzardError as exc:
            if strict:
                raise RealmResolutionError(
                    f"No he podido consultar el reino {slug!r}: {exc}"
                ) from exc
            log.warning("Reino %s omitido: %s", slug, exc)
            continue

        if realm_id is None:
            # El slug no le suena a Blizzard. Segunda via: buscar el slug
            # oficial por nombre en el indice, que se pide una sola vez.
            if indice is None:
                indice = client.realm_index()
            oficial = _buscar_en_indice(indice, slug)
            if oficial and oficial != slug:
                try:
                    realm_id = client.connected_realm_id_for(oficial)
                except BlizzardError as exc:
                    log.warning("Reino %s (%s) omitido: %s", slug, oficial, exc)

        if realm_id is None:
            if strict:
                raise RealmResolutionError(
                    f"Blizzard no conoce ningun reino llamado {slug!r}. "
                    "Comprueba el nombre en el juego."
                )
            log.warning("Reino %s omitido: Blizzard no lo conoce.", slug)
            continue

        resultado[slug] = realm_id
        cache.set(slug, realm_id)

    return resultado


def _buscar_en_indice(indice: list[dict], slug: str) -> str | None:
    """Slug oficial del reino cuyo nombre o slug coincide, o None.

    La comparacion se hace solo con letras y numeros, sin guiones ni espacios:
    si se llega hasta aqui es porque el slug deducido del nombre no ha valido,
    asi que comparar separadores seria repetir el mismo error.
    """
    objetivo = _solo_alfanumerico(slug)
    for realm in indice:
        candidatos = {
            _solo_alfanumerico(str(realm.get("slug", ""))),
            _solo_alfanumerico(str(realm.get("name", ""))),
        }
        if objetivo in candidatos:
            oficial = realm.get("slug")
            return oficial if isinstance(oficial, str) else None
    return None


def _solo_alfanumerico(texto: str) -> str:
    return "".join(c for c in slugify_realm(texto) if c.isalnum())
