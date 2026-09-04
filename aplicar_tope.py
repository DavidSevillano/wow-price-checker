"""Aplica a config.yaml el cambio de tope que pide una issue.

    py aplicar_tope.py < cuerpo.md         # el cuerpo de la issue por stdin
    py aplicar_tope.py --dry-run < x.md    # sin escribir nada

Lee el cuerpo de la issue, cambia el tope, y escribe el fichero. Por stdout
sale el comentario en markdown que el workflow publica en la issue, tanto si va
bien como si va mal; el codigo de salida es lo que le dice al workflow si
commitear y cerrar (0) o dejarla abierta (1).

Hay tres emisores de ese cuerpo --el formulario de texto al que apunta el aviso
de Discord, el de desplegables, y la app del movil-- y los tres generan
exactamente el mismo markdown. Por eso aqui hay un solo parser.

Va aparte de main.py por lo mismo que datos_app.py: main.py manda las alertas y
no conviene tocarlo para esto.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wowalerts.config import Config, ConfigError, load_config
from wowalerts.topes import TopeError, cambiar_tope

EXIT_OK = 0
EXIT_ERROR = 1

# Las etiquetas de los campos, que es como GitHub titula cada bloque del cuerpo.
# Son el contrato con las plantillas de .github/ISSUE_TEMPLATE y con la app: si
# cambias una aqui, cambiala en los tres sitios.
CAMPO_OBJETO = "Objeto"
CAMPO_ILVL = "ilvl"
CAMPO_TOPE = "Tope nuevo, en oro"

# Lo que escribe GitHub cuando dejas en blanco un campo opcional.
SIN_RESPUESTA = "_No response_"

# La opcion del desplegable para los objetos que no escalan.
SIN_ILVL = "sin ilvl"


@dataclass(frozen=True)
class Peticion:
    objeto: str
    ilvl: int | None
    tope: int


def _campos(cuerpo: str) -> dict[str, str]:
    """Parte el cuerpo en '### Etiqueta' -> valor.

    GitHub renderiza los formularios con la ETIQUETA del campo como encabezado,
    no con su id, asi que es la etiqueta lo que hay que buscar.
    """
    trozos = re.split(r"^###[ \t]*(.+?)[ \t]*$", cuerpo, flags=re.MULTILINE)
    # split deja [previo, etiqueta1, valor1, etiqueta2, valor2, ...]
    return {
        trozos[i].strip(): trozos[i + 1].strip()
        for i in range(1, len(trozos) - 1, 2)
    }


def _entero(texto: str, campo: str) -> int:
    """Un entero escrito por una persona en un movil.

    Se admiten separadores de miles y un 'g' detras, porque escribir '4.000 g'
    es lo natural y rechazarlo obligaria a repetir la issue entera.
    """
    limpio = re.sub(r"[.,\s]", "", texto)
    limpio = re.sub(r"[gG]$", "", limpio)
    if not re.fullmatch(r"\d+", limpio):
        raise TopeError(f"{campo!r}: {texto!r} no es un numero entero.")
    return int(limpio)


def parsear(cuerpo: str) -> Peticion:
    """La peticion que lleva dentro el cuerpo de una issue."""
    campos = _campos(cuerpo)

    for etiqueta in (CAMPO_OBJETO, CAMPO_ILVL, CAMPO_TOPE):
        if etiqueta not in campos:
            raise TopeError(
                f"Falta el campo {etiqueta!r} en la issue. Usa la plantilla de "
                "'Ajustar un tope' en vez de una issue en blanco."
            )

    objeto = campos[CAMPO_OBJETO]
    if not objeto:
        raise TopeError(f"El campo {CAMPO_OBJETO!r} viene vacio.")

    bruto = campos[CAMPO_ILVL]
    if not bruto or bruto == SIN_RESPUESTA or bruto.lower().startswith(SIN_ILVL):
        ilvl = None
    else:
        ilvl = _entero(bruto, CAMPO_ILVL)

    return Peticion(objeto, ilvl, _entero(campos[CAMPO_TOPE], CAMPO_TOPE))


def _cargar(texto: str) -> Config:
    """load_config solo lee de disco, asi que el texto pasa por un temporal."""
    carpeta = Path(tempfile.mkdtemp())
    ruta = carpeta / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return load_config(ruta)


def _topes(config: Config) -> dict[tuple[str, int | None], int]:
    """Todos los topes de una config, aplanados para poder compararlos."""
    salida: dict[tuple[str, int | None], int] = {}
    for regla in config.items:
        if regla.max_price is not None:
            salida[(regla.name, None)] = regla.max_price
        for ilvl, tope in regla.max_price_by_ilvl.items():
            salida[(regla.name, ilvl)] = tope
    return salida


def verificar(viejo: str, nuevo: str, peticion: Peticion) -> None:
    """La red de seguridad que hace seguro editar YAML por texto.

    Editar con expresiones regulares da miedo, con razon. Esto lo convierte en
    un riesgo acotado: si la edicion ha roto el fichero, no ha puesto el tope
    pedido, o ha movido cualquier otro, se aborta antes de commitear nada.
    """
    try:
        antes = _topes(_cargar(viejo))
        despues = _topes(_cargar(nuevo))
    except ConfigError as fallo:
        raise TopeError(
            f"El config.yaml resultante no es valido, asi que no lo toco: {fallo}"
        ) from fallo

    clave = (peticion.objeto, peticion.ilvl)
    if despues.get(clave) != peticion.tope:
        raise TopeError(
            f"El tope de {peticion.objeto!r} no ha quedado en {peticion.tope}. "
            "No cambio nada."
        )

    movidos = [
        k for k in set(antes) | set(despues)
        if k != clave and antes.get(k) != despues.get(k)
    ]
    if movidos:
        detalle = ", ".join(f"{o} ilvl {i}" for o, i in sorted(movidos, key=str))
        raise TopeError(
            f"La edicion ha movido otro tope ademas del pedido ({detalle}), "
            "asi que no la aplico."
        )


def _oro(cantidad: int) -> str:
    """120000 -> '120.000' (separador de miles a la espanola)."""
    return f"{cantidad:,}".replace(",", ".")


def _ok(peticion: Peticion, viejo: int) -> str:
    donde = f" · ilvl {peticion.ilvl}" if peticion.ilvl is not None else ""
    return (
        "✅ **Tope actualizado.**\n\n"
        "```\n"
        f"{peticion.objeto}{donde}\n"
        f"{_oro(viejo)} → {_oro(peticion.tope)} de oro\n"
        "```\n\n"
        "Entra en vigor en la pasada siguiente, como mucho dentro de una hora."
    )


def _error(fallo: Exception) -> str:
    return (
        "❌ **No he cambiado nada.**\n\n"
        f"{fallo}\n\n"
        "Corrige y abre otra issue; esta se queda abierta para que puedas verla."
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aplica a config.yaml el cambio de tope que pide una issue.",
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

    try:
        peticion = parsear(sys.stdin.read())
        texto = ruta.read_text(encoding="utf-8")
        nuevo, viejo = cambiar_tope(texto, peticion.objeto, peticion.ilvl, peticion.tope)
        verificar(texto, nuevo, peticion)
    except (TopeError, ConfigError, OSError) as fallo:
        print(_error(fallo))
        return EXIT_ERROR

    if not args.dry_run:
        ruta.write_text(nuevo, encoding="utf-8")

    print(_ok(peticion, viejo))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
