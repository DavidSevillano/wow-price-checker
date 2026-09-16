"""Anadir un objeto vigilado a config.yaml, sin tocar nada mas.

No pasa por PyYAML, por lo mismo que topes.py: cargar y volcar devolveria un
YAML equivalente pero reformateado y sin un solo comentario, y los comentarios
de config.yaml son la mitad de su valor.

Asi que se edita el texto: se copia la tabla del objeto del que quieres partir,
se escribe el bloque nuevo detras, y el resto del fichero queda byte a byte
identico.

La red de seguridad esta fuera, en anadir_objeto.py: recarga el resultado con
load_config() y comprueba que no ha cambiado ningun objeto anterior antes de
dejar que se commitee.
"""

from __future__ import annotations

import re

from .topes import bloque_de

__all__ = ["ObjetoError", "anadir_equipo", "anadir_patron", "tabla_de"]


class ObjetoError(Exception):
    """No se puede anadir el objeto. El mensaje explica por que."""


def tabla_de(texto: str, objeto: str) -> str:
    """Las lineas de 'max_price_by_ilvl' de ese objeto, tal y como estan.

    Se copia el texto y no los numeros porque asi la tabla nueva sale con el
    mismo formato que las demas, y el diff se lee.
    """
    inicio, fin = bloque_de(texto, objeto)
    bloque = texto[inicio:fin]

    clave = bloque.find("max_price_by_ilvl")
    if clave == -1:
        raise ObjetoError(
            f"{objeto!r} lleva un precio unico y no tabla por ilvl, asi que no "
            "hay topes que copiar. Elige una pieza de equipo."
        )

    cierra = bloque.find("}", clave)
    if cierra == -1:
        raise ObjetoError(
            f"No entiendo la tabla 'max_price_by_ilvl' de {objeto!r}. Tiene que "
            "ir entre llaves, como { 295: 9000, 311: 90000 }."
        )

    principio = bloque.rfind("\n", 0, clave) + 1
    final = bloque.find("\n", cierra)
    return bloque[principio:] if final == -1 else bloque[principio:final + 1]
