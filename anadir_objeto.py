"""Anade a config.yaml el objeto nuevo que pide una issue.

    py anadir_objeto.py < cuerpo.md         # el cuerpo de la issue por stdin
    py anadir_objeto.py --dry-run < x.md    # sin escribir nada

Hermano de aplicar_tope.py: aquel mueve el tope de un objeto que ya vigilas,
este anade uno que no estaba. Por stdout sale el comentario en markdown que el
workflow publica en la issue, y el codigo de salida le dice si commitear (0) o
dejarla abierta (1).

Hay dos emisores del cuerpo --la app del movil y el formulario de GitHub-- y
los dos generan el mismo markdown, asi que aqui hay un solo parser.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from wowalerts.config import Config, ConfigError, ItemRule, load_config
from wowalerts.objetos import ObjetoError, anadir_equipo, anadir_patron
from wowalerts.topes import TopeError

EXIT_OK = 0
EXIT_ERROR = 1

# Las etiquetas de los campos, que es como GitHub titula cada bloque del cuerpo.
# Son el contrato con .github/ISSUE_TEMPLATE/objeto.yml y con la app: si cambias
# una aqui, cambiala en los tres sitios.
CAMPO_OBJETO = "Objeto"
CAMPO_TIPO = "Tipo"
CAMPO_COPIAR = "Copiar topes de"
CAMPO_TOPE = "Tope, en oro"

# Lo que escribe GitHub cuando dejas en blanco un campo opcional.
SIN_RESPUESTA = "_No response_"

EQUIPO = "equipo"
PATRON = "patron"

# El id que lleva dentro un enlace de Wowhead, que es lo que se pega desde el
# movil: https://www.wowhead.com/es/item=258126/patron-...
_ENLACE = re.compile(r"item=(\d+)")


@dataclass(frozen=True)
class Peticion:
    # Lo escrito en el campo: un enlace de Wowhead, un id, o el nombre en ingles.
    objeto: str
    tipo: str
    copiar_de: str | None
    tope: int | None


def _campos(cuerpo: str) -> dict[str, str]:
    """Parte el cuerpo en '### Etiqueta' -> valor.

    GitHub renderiza los formularios con la ETIQUETA del campo como encabezado,
    no con su id, asi que es la etiqueta lo que hay que buscar.
    """
    trozos = re.split(r"^###[ \t]*(.+?)[ \t]*$", cuerpo, flags=re.MULTILINE)
    return {
        trozos[i].strip(): trozos[i + 1].strip()
        for i in range(1, len(trozos) - 1, 2)
    }


def _entero(texto: str, campo: str) -> int:
    """Un entero escrito por una persona en un movil.

    Se admiten separadores de miles y un 'g' detras, porque escribir '40.000 g'
    es lo natural y rechazarlo obligaria a repetir la issue entera.
    """
    limpio = re.sub(r"[.,\s]", "", texto)
    limpio = re.sub(r"[gG]$", "", limpio)
    if not re.fullmatch(r"\d+", limpio):
        raise ObjetoError(f"{campo!r}: {texto!r} no es un numero entero.")
    return int(limpio)


def _relleno(campos: dict[str, str], etiqueta: str) -> str | None:
    """El valor de un campo opcional, o None si se dejo en blanco."""
    valor = campos.get(etiqueta, "").strip()
    return None if not valor or valor == SIN_RESPUESTA else valor


def _tipo(texto: str) -> str:
    limpio = texto.strip().lower()
    if limpio.startswith("equipo"):
        return EQUIPO
    # Por el principio, que el desplegable dice "Patron" con tilde o sin ella.
    if limpio.startswith("patr"):
        return PATRON
    raise ObjetoError(
        f"No entiendo el tipo {texto!r}. Tiene que ser 'Equipo (tabla por ilvl)' "
        "o 'Patron o receta (precio unico)'. Las mascotas y las monturas se "
        "siguen anadiendo a mano en config.yaml."
    )


def id_de(texto: str) -> int | None:
    """El item id que lleva dentro lo escrito, si lo lleva.

    Vale el enlace de Wowhead y el numero suelto. Cualquier otra cosa se toma
    por el nombre del objeto en ingles.
    """
    enlace = _ENLACE.search(texto)
    if enlace is not None:
        return int(enlace.group(1))
    limpio = texto.strip()
    return int(limpio) if limpio.isdigit() else None


def parsear(cuerpo: str) -> Peticion:
    """La peticion que lleva dentro el cuerpo de una issue."""
    campos = _campos(cuerpo)

    for etiqueta in (CAMPO_OBJETO, CAMPO_TIPO):
        if etiqueta not in campos:
            raise ObjetoError(
                f"Falta el campo {etiqueta!r} en la issue. Usa la plantilla de "
                "'Anadir un objeto' en vez de una issue en blanco."
            )

    objeto = _relleno(campos, CAMPO_OBJETO)
    if objeto is None:
        raise ObjetoError(f"El campo {CAMPO_OBJETO!r} viene vacio.")

    tipo = _tipo(campos[CAMPO_TIPO])
    copiar_de = _relleno(campos, CAMPO_COPIAR)
    tope = _relleno(campos, CAMPO_TOPE)

    if tipo == EQUIPO:
        if copiar_de is None:
            raise ObjetoError(
                "Una pieza de equipo lleva tabla por ilvl, asi que necesito de "
                f"que objeto copiarla: rellena {CAMPO_COPIAR!r}."
            )
        return Peticion(objeto, EQUIPO, copiar_de, None)

    if tope is None:
        raise ObjetoError(
            f"Un patron lleva precio unico: rellena {CAMPO_TOPE!r}."
        )
    return Peticion(objeto, PATRON, None, _entero(tope, CAMPO_TOPE))
