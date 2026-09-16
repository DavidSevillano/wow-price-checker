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

    # Anclado al principio de linea para que un comentario que solo mencione
    # 'max_price_by_ilvl' --sin ser la clave de verdad-- no cuele.
    clave_match = re.search(r"^[ \t]*max_price_by_ilvl:", bloque, re.MULTILINE)
    if clave_match is None:
        raise ObjetoError(
            f"{objeto!r} lleva un precio unico y no tabla por ilvl, asi que no "
            "hay topes que copiar. Elige una pieza de equipo."
        )
    clave = clave_match.start()

    cierra = bloque.find("}", clave)
    if cierra == -1:
        raise ObjetoError(
            f"No entiendo la tabla 'max_price_by_ilvl' de {objeto!r}. Tiene que "
            "ir entre llaves, como { 295: 9000, 311: 90000 }."
        )

    principio = bloque.rfind("\n", 0, clave) + 1
    final = bloque.find("\n", cierra)
    return bloque[principio:] if final == -1 else bloque[principio:final + 1]


def anadir_equipo(texto: str, nombre: str, item_id: int, copiar_de: str) -> str:
    """config.yaml con una pieza nueva, con los topes de `copiar_de`.

    Va justo detras del objeto del que copia para que las tablas iguales queden
    juntas: asi se ve de un vistazo que dos piezas comparten precios.
    """
    _rechazar_comillas(nombre)
    tabla = tabla_de(texto, copiar_de)
    bloque = f"  - name: {_cita(nombre)}\n    item_id: {item_id}\n{tabla}"
    return _insertar(texto, _fin_del_contenido(texto, *bloque_de(texto, copiar_de)), bloque)


def _cita(texto: str) -> str:
    """Un escalar YAML entrecomillado: los nombres llevan apostrofos y dos puntos."""
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rechazar_comillas(nombre: str) -> None:
    """Un nombre con comillas dobles o barras invertidas no se puede admitir.

    _cita lo escribiria escapado, pero topes._patron_nombre busca el nombre
    literal en 'name:' y no sabe de escapes: ese objeto no se podria encontrar
    nunca mas para cambiarle el tope.
    """
    if '"' in nombre or "\\" in nombre:
        raise ObjetoError(
            f"{nombre!r} lleva comillas dobles o una barra invertida, y luego no "
            "se podria volver a encontrar para cambiarle el tope. Anadelo a mano "
            "en config.yaml."
        )


def _fin_del_contenido(texto: str, inicio: int, fin: int) -> int:
    """Donde acaba la ultima linea que es de verdad, dentro de [inicio, fin).

    [inicio, fin) llega hasta el objeto siguiente, y por el camino se lleva las
    lineas en blanco y los comentarios que hay entre medias. Esos comentarios
    suelen abrir la seccion de detras --'Monturas caras'--, asi que lo nuevo
    tiene que ir delante de ellos y no debajo.
    """
    lineas = texto[inicio:fin].splitlines(keepends=True)
    while lineas and (not lineas[-1].strip() or lineas[-1].lstrip().startswith("#")):
        lineas.pop()
    return inicio + sum(len(linea) for linea in lineas)


def _insertar(texto: str, donde: int, bloque: str) -> str:
    """Mete el bloque en `donde`, con una linea en blanco delante.

    Lo que habia detras --la linea en blanco, un comentario, el objeto
    siguiente-- sigue detras tal cual estaba.
    """
    antes = texto[:donde]
    if not antes.endswith("\n"):
        antes += "\n"
    return antes + "\n" + bloque + texto[donde:]


# El renglon que abre cualquier objeto de 'items:'. La lista de personajes no
# casa: sus entradas son nombres sueltos, sin 'name:'.
_APERTURA = re.compile(r"^[ \t]*-[ \t]+name:[ \t]*(.+?)[ \t]*$", re.MULTILINE)

_REPOSTEABLE = re.compile(r"^[ \t]*repostear:[ \t]*true[ \t]*(?:#.*)?$", re.MULTILINE)

# La siguiente clave de primer nivel del YAML, como 'orden_personajes:'. No
# casa con un comentario ni con una linea sangrada, que es lo que forma el
# resto del bloque de un objeto.
_CLAVE_DE_PRIMER_NIVEL = re.compile(r"^[^ \t\n#]", re.MULTILINE)


def anadir_patron(texto: str, nombre: str, item_id: int, tope: int) -> str:
    """config.yaml con un patron nuevo, con precio unico.

    Lleva las dos banderas que llevan los patrones que ya vigilas: sin avisos de
    undercut --de una receta no quieres saber que alguien se ha puesto debajo--
    pero si reposteable con la tecla del addon.
    """
    _rechazar_comillas(nombre)
    bloque = (
        f"  - name: {_cita(nombre)}\n"
        f"    item_id: {item_id}\n"
        f"    max_price: {tope}\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    return _insertar(texto, _tras_el_ultimo_reposteable(texto), bloque)


def _tras_el_ultimo_reposteable(texto: str) -> int:
    """Donde acaba el ultimo objeto reposteable, o el ultimo de la lista.

    Los patrones viven juntos en config.yaml, antes de las monturas y las
    mascotas, que son trampas para el error de otro y no cosas que repostees.

    Trabaja con posiciones y no con nombres reconstruidos: una linea 'name:'
    con un comentario detras, o un nombre con comillas escapadas, no se puede
    volver a buscar de forma fiable con bloque_de.
    """
    aperturas = list(_APERTURA.finditer(texto))
    if not aperturas:
        raise ObjetoError("No encuentro ningun objeto en 'items:' de config.yaml.")

    ultimo_bloque = None
    ultimo_reposteable = None
    for i, apertura in enumerate(aperturas):
        siguiente_apertura = (
            aperturas[i + 1].start() if i + 1 < len(aperturas) else len(texto)
        )
        clave_siguiente = _CLAVE_DE_PRIMER_NIVEL.search(texto, apertura.end())
        fin = min(
            siguiente_apertura,
            clave_siguiente.start() if clave_siguiente else len(texto),
        )
        ultimo_bloque = (apertura.start(), fin)
        if _REPOSTEABLE.search(texto[apertura.start():fin]):
            ultimo_reposteable = ultimo_bloque

    inicio, fin = ultimo_reposteable if ultimo_reposteable else ultimo_bloque
    return _fin_del_contenido(texto, inicio, fin)
