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


def resolver(client: BlizzardClient, peticion: Peticion) -> tuple[str, int]:
    """El nombre en ingles y el id del objeto que pide la issue.

    El movil no tiene credenciales de Blizzard: por eso el campo viaja como
    texto y la traduccion a id se hace aqui, en Actions, que es donde estan los
    secretos.
    """
    item_id = id_de(peticion.objeto)
    if item_id is not None:
        nombre = client.item_name(item_id)
        if nombre is None:
            raise ObjetoError(
                f"Blizzard no conoce ningun objeto con id {item_id}. Comprueba "
                "el enlace: el numero es el que va detras de 'item=' en Wowhead."
            )
        return nombre, item_id

    nombre = peticion.objeto.strip()
    item_id = client.search_item_id(nombre)
    if item_id is None:
        raise ObjetoError(
            f"Blizzard no encuentra ningun objeto que se llame {nombre!r}. Tiene "
            "que ser el nombre en ingles, igual que en el juego; si el objeto es "
            "recien salido, pega mejor su enlace de Wowhead."
        )
    return nombre, item_id


def comprobar_nuevo(config: Config, nombre: str, item_id: int) -> None:
    """Que el objeto no estuviera vigilado ya, ni por nombre ni por id."""
    for regla in config.items:
        if regla.name.strip().lower() == nombre.strip().lower():
            raise ObjetoError(
                f"{regla.name!r} ya esta vigilado. Para cambiarle el tope usa el "
                "boton de la app, o la plantilla 'Ajustar un tope'."
            )
        if regla.item_id is not None and regla.item_id == item_id:
            raise ObjetoError(
                f"El objeto {item_id} ya esta vigilado, con el nombre "
                f"{regla.name!r}. Para cambiarle el tope usa el boton de la app."
            )


def _cargar(texto: str) -> Config:
    """load_config solo lee de disco, asi que el texto pasa por un temporal."""
    ruta = Path(tempfile.mkdtemp()) / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return load_config(ruta)


def verificar(
    viejo: str, nuevo: str, nombre: str, item_id: int, peticion: Peticion
) -> ItemRule:
    """La red de seguridad que hace seguro editar YAML por texto.

    Si la edicion ha roto el fichero, no ha dejado el objeto pedido, o ha
    tocado cualquier otro, se aborta antes de commitear nada.

    Devuelve la regla nueva, que es lo que el comentario de la issue ensena.
    """
    try:
        antes = {regla.name: regla for regla in _cargar(viejo).items}
        despues = {regla.name: regla for regla in _cargar(nuevo).items}
    except ConfigError as fallo:
        raise ObjetoError(
            f"El config.yaml resultante no es valido, asi que no lo toco: {fallo}"
        ) from fallo

    regla = despues.get(nombre)
    if regla is None:
        raise ObjetoError(f"{nombre!r} no ha quedado en config.yaml. No anado nada.")
    if regla.item_id != item_id:
        raise ObjetoError(
            f"{nombre!r} no ha quedado con el id {item_id}. No anado nada."
        )

    if peticion.tipo == EQUIPO:
        origen = antes[peticion.copiar_de]
        if dict(regla.max_price_by_ilvl) != dict(origen.max_price_by_ilvl):
            raise ObjetoError(
                f"Los topes de {nombre!r} no han quedado como los de "
                f"{peticion.copiar_de!r}. No anado nada."
            )
    elif (
        regla.max_price != peticion.tope
        or regla.avisar_undercut
        or not regla.se_repostea
    ):
        raise ObjetoError(
            f"{nombre!r} no ha quedado con el precio y las banderas pedidos. "
            "No anado nada."
        )

    movidos = [n for n in antes if antes[n] != despues.get(n)]
    if movidos:
        raise ObjetoError(
            "La edicion ha tocado otros objetos ademas del nuevo ("
            + ", ".join(sorted(movidos))
            + "), asi que no la aplico."
        )

    return regla


def _oro(cantidad: int) -> str:
    """40000 -> '40.000' (separador de miles a la espanola)."""
    return f"{cantidad:,}".replace(",", ".")


def _ok(nombre: str, item_id: int, regla: ItemRule) -> str:
    if regla.max_price is not None:
        topes = f"{_oro(regla.max_price)} de oro"
    else:
        topes = "\n".join(
            f"ilvl {ilvl}: {_oro(tope)}"
            for ilvl, tope in sorted(regla.max_price_by_ilvl.items())
        )
    return (
        "✅ **Objeto anadido.**\n\n"
        "```\n"
        f"{nombre}  (id {item_id})\n"
        f"{topes}\n"
        "```\n\n"
        "Empieza a vigilarse en la pasada siguiente, como mucho dentro de una "
        "hora, y a partir de ahi sale en la app."
    )


def _error(fallo: Exception) -> str:
    return (
        "❌ **No he anadido nada.**\n\n"
        f"{fallo}\n\n"
        "Corrige y abre otra issue; esta se queda abierta para que puedas verla."
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anade a config.yaml el objeto que pide una issue.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribe el fichero: solo dice que haria.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    ruta = Path(args.config)
    load_dotenv(Path(__file__).resolve().parent / ".env")

    try:
        peticion = parsear(sys.stdin.read())
        texto = ruta.read_text(encoding="utf-8")
        config = load_config(ruta)
        client = BlizzardClient(
            client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
            client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
            region=config.region,
            locale=config.locale,
            timeout=config.settings.request_timeout,
        )
        nombre, item_id = resolver(client, peticion)
        comprobar_nuevo(config, nombre, item_id)
        if peticion.tipo == EQUIPO:
            nuevo = anadir_equipo(texto, nombre, item_id, peticion.copiar_de)
        else:
            nuevo = anadir_patron(texto, nombre, item_id, peticion.tope)
        regla = verificar(texto, nuevo, nombre, item_id, peticion)
    except (
        ObjetoError,
        TopeError,
        ConfigError,
        BlizzardAuthError,
        BlizzardError,
        OSError,
    ) as fallo:
        print(_error(fallo))
        return EXIT_ERROR

    if not args.dry_run:
        ruta.write_text(nuevo, encoding="utf-8")

    print(_ok(nombre, item_id, regla))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
