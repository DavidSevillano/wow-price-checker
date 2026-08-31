"""Sube tus subastas al repositorio para que el vigilante las conozca.

Lee lo que el addon ha volcado en SavedVariables, lo escribe normalizado en
mis_subastas.json y, si ha cambiado algo, lo commitea y lo empuja. Pensado para
ejecutarse desatendido desde una tarea programada, asi que cuando no hay nada
que hacer no hace nada.

Uso:

    py sync_subastas.py                 # leer, escribir y subir
    py sync_subastas.py --dry-run       # solo decir que haria
    py sync_subastas.py --no-push       # commit local, sin subir
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from wowalerts.misubastas import MisSubastasError, escribir_snapshot, leer_de_wow
from wowalerts.personajes import escribir_personajes, leer_personajes

log = logging.getLogger("sync")

EXIT_OK = 0
EXIT_ERROR = 1

# Sitios donde suele estar WoW. La primera que exista gana.
RUTAS_HABITUALES = (
    r"D:\Juegos\World of Warcraft\_retail_",
    r"C:\Program Files (x86)\World of Warcraft\_retail_",
    r"C:\Program Files\World of Warcraft\_retail_",
    r"D:\World of Warcraft\_retail_",
    r"D:\Games\World of Warcraft\_retail_",
)


def detectar_wow_root(candidatas=RUTAS_HABITUALES) -> Path | None:
    """Primera carpeta de WoW que exista y tenga WTF dentro."""
    for ruta in candidatas:
        path = Path(ruta)
        if (path / "WTF").is_dir():
            return path
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync_subastas.py",
        description="Sube tus subastas de WoW al repositorio.",
    )
    parser.add_argument(
        "--wow-root",
        help="Carpeta _retail_ de WoW. Si no se indica, se busca en los sitios "
        "habituales.",
    )
    parser.add_argument(
        "--salida",
        default="mis_subastas.json",
        help="Fichero donde escribir el volcado (por defecto: mis_subastas.json).",
    )
    parser.add_argument(
        "--personajes",
        default="mis_personajes.json",
        help="Fichero con la lista de tus personajes, para que los avisos de "
        "chollo digan con quien entrar a comprarlos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dice que haria, sin escribir ni subir nada.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Hace el commit pero no lo sube.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def git(*args: str) -> subprocess.CompletedProcess:
    """Ejecuta git capturando la salida, para que el log sea legible."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def subir(ficheros: list[str], push: bool) -> int:
    """Commitea lo que haya cambiado y, si toca, lo sube."""
    add = git("add", *ficheros)
    if add.returncode != 0:
        log.error("git add ha fallado: %s", add.stderr.strip())
        return EXIT_ERROR

    commit = git("commit", "-m", "Actualiza el volcado de mis subastas")
    if commit.returncode != 0:
        # Sin cambios que commitear es un caso normal, no un fallo.
        if "nothing to commit" in commit.stdout:
            log.info("Nada que commitear.")
            return EXIT_OK
        log.error(
            "git commit ha fallado: %s",
            commit.stderr.strip() or commit.stdout.strip(),
        )
        return EXIT_ERROR

    log.info("Commit hecho.")
    if not push:
        return EXIT_OK

    empuje = git("push")
    if empuje.returncode != 0:
        log.error(
            "git push ha fallado: %s\n"
            "Si es un problema de credenciales, haz un push a mano una vez para "
            "que el gestor de credenciales de Git las recuerde.",
            empuje.stderr.strip(),
        )
        return EXIT_ERROR

    log.info("Subido a GitHub.")
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    wow_root = Path(args.wow_root) if args.wow_root else detectar_wow_root()
    if wow_root is None:
        log.error(
            "No encuentro la carpeta de WoW. Pasala a mano:\n"
            r'  py sync_subastas.py --wow-root "D:\ruta\World of Warcraft\_retail_"'
        )
        return EXIT_ERROR

    subastas = leer_de_wow(wow_root)
    log.info("%s subasta(s) tuyas leidas de %s.", len(subastas), wow_root)

    personajes = leer_personajes(wow_root)

    if args.dry_run:
        log.info("--dry-run: no escribo ni subo nada.")
        return EXIT_OK

    cambiados = []
    if escribir_snapshot(args.salida, subastas):
        cambiados.append(args.salida)
    if escribir_personajes(args.personajes, personajes):
        cambiados.append(args.personajes)

    if not cambiados:
        log.info("Sin cambios respecto a lo ya subido.")
        return EXIT_OK

    log.info("Actualizado: %s.", ", ".join(cambiados))
    return subir(cambiados, push=not args.no_push)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        stream=sys.stdout,
    )
    try:
        return run(args)
    except MisSubastasError as exc:
        log.error("%s", exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
