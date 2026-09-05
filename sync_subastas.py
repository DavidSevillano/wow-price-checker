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
import os
import platform
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
import sys
from pathlib import Path

from wowalerts.journalator import (
    apuntes_de_wow,
    encontrar_journalator,
    escribir_resumen,
    ventas_de_wow,
)
from wowalerts.misubastas import (
    MisSubastasError,
    escribir_snapshot,
    cuentas_con_addon_viejo,
    encontrar_savedvariables,
    leer_canceladas_de_wow,
    volcado_atrasado,
    leer_de_wow,
)
from wowalerts.personajes import escribir_personajes, leer_personajes

log = logging.getLogger("sync")

EXIT_OK = 0
EXIT_ERROR = 1

# Sitios donde suele estar WoW. La primera que exista gana. Las de Linux son
# para la Steam Deck, donde WoW vive en la tarjeta SD o dentro del prefijo de
# Proton, segun como lo hayas instalado.
RUTAS_HABITUALES = (
    r"D:\Juegos\World of Warcraft\_retail_",
    r"C:\Program Files (x86)\World of Warcraft\_retail_",
    r"C:\Program Files\World of Warcraft\_retail_",
    r"D:\World of Warcraft\_retail_",
    r"D:\Games\World of Warcraft\_retail_",
    "/run/media/deck/EmuSD/World of Warcraft/_retail_",
    "~/Games/world-of-warcraft/drive_c/Program Files (x86)/World of Warcraft/_retail_",
    "~/.local/share/lutris/runners/wine/World of Warcraft/_retail_",
)


def detectar_wow_root(candidatas=RUTAS_HABITUALES) -> Path | None:
    """Primera carpeta de WoW que exista y tenga WTF dentro."""
    for ruta in candidatas:
        path = Path(ruta).expanduser()
        if (path / "WTF").is_dir():
            return path
    return None


def nombre_de_maquina() -> str:
    """Nombre corto de este equipo, para que cada uno escriba su propio fichero.

    Si el PC y la Steam Deck compartieran fichero, cada uno borraria al subir
    los personajes con los que has jugado en el otro.
    """
    crudo = platform.node().split(".")[0] or "equipo"
    limpio = re.sub(r"[^a-zA-Z0-9_-]+", "-", crudo).strip("-").lower()
    return limpio or "equipo"


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
        default="mis_subastas",
        help="Carpeta donde escribir el volcado (por defecto: mis_subastas). "
        "Dentro, un fichero por maquina.",
    )
    parser.add_argument(
        "--personajes",
        default="mis_personajes",
        help="Carpeta con la lista de tus personajes, para que los avisos de "
        "chollo digan con quien entrar a comprarlos.",
    )
    parser.add_argument(
        "--ventas",
        default="mis_ventas",
        help="Carpeta con el resumen de lo que has vendido, sacado del addon "
        "Journalator. Es lo que alimenta el panel de ventas por reino.",
    )
    parser.add_argument(
        "--maquina",
        default=None,
        help="Nombre de este equipo. Por defecto el del sistema. Cada maquina "
        "escribe su propio fichero para no pisar la de las demas.",
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
    parser.add_argument(
        "--vigilar",
        action="store_true",
        help="No termina: sincroniza cada vez que WoW guarda los datos del "
        "addon, que es al salir al selector de personajes o cerrar el juego.",
    )
    parser.add_argument(
        "--vigilar-cada",
        type=int,
        default=5,
        help="Segundos entre comprobaciones con --vigilar (por defecto: 5).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


# La tarea programada corre con pythonw.exe, que no tiene consola. En Windows,
# un proceso de consola lanzado desde ahi se abre una ventana propia: con cuatro
# llamadas a git por pasada, eso son cuatro parpadeos cada quince minutos
# mientras juegas. Fuera de Windows la constante no existe y un 0 no cambia nada.
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(*args: str) -> subprocess.CompletedProcess:
    """Ejecuta git capturando la salida, para que el log sea legible."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        creationflags=SIN_VENTANA,
    )


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

    # Antes de subir, traerse lo que haya subido la otra maquina. Sin esto, el
    # primer push de la Steam Deck rebota en cuanto el PC haya subido algo.
    #
    # Con --autostash porque esto corre desatendido: si te has dejado algo a
    # medias en la carpeta, el rebase se negaria a empezar y la sincronizacion
    # se quedaria parada sin que te enteres.
    traer = git("pull", "--rebase", "--autostash")
    if traer.returncode != 0:
        log.error(
            "git pull --rebase ha fallado: %s\n"
            "Resuelvelo a mano en la carpeta del proyecto y vuelve a intentarlo.",
            traer.stderr.strip(),
        )
        return EXIT_ERROR

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


# Cuanto se da por muerto un cerrojo que nadie ha soltado. Una sincronizacion
# tarda segundos; si lleva mas de esto, quien lo cogio ya no existe (lo mataron,
# se apago el equipo a media pasada) y seguir respetandolo dejaria la
# sincronizacion parada para siempre.
CERROJO_CADUCA_EN = 600


@contextmanager
def en_exclusiva(carpeta: Path):
    """Deja pasar una sola sincronizacion a la vez.

    Hay dos disparadores --el vigilante y la tarea programada-- y ambos hacen
    git en la misma carpeta. Si coinciden, el rebase de uno se encuentra el del
    otro a medias y falla con errores que no dicen nada ("Cannot rebase onto
    multiple branches"). No se pierde nada, porque la pasada siguiente lo
    recoge, pero ensucia el log justo donde uno mira cuando algo va mal.
    """
    cerrojo = carpeta / "sync.lock"
    cerrojo.parent.mkdir(parents=True, exist_ok=True)
    try:
        edad = time.time() - cerrojo.stat().st_mtime
        if edad > CERROJO_CADUCA_EN:
            log.warning("Habia un cerrojo de hace %.0f s; lo doy por muerto.", edad)
            cerrojo.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        descriptor = os.open(cerrojo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return

    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield True
    finally:
        cerrojo.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:
    with en_exclusiva(Path(__file__).resolve().parent / ".state") as mio:
        if not mio:
            log.info("Ya hay otra sincronizacion en marcha; me la salto.")
            return EXIT_OK
        return _sincronizar(args)


def _sincronizar(args: argparse.Namespace) -> int:
    wow_root = Path(args.wow_root) if args.wow_root else detectar_wow_root()
    if wow_root is None:
        log.error(
            "No encuentro la carpeta de WoW. Pasala a mano:\n"
            r'  py sync_subastas.py --wow-root "D:\ruta\World of Warcraft\_retail_"'
        )
        return EXIT_ERROR

    # Journalator va por su cuenta: lo lleva otro addon y tiene historial aunque
    # el nuestro no haya volcado nada todavia.
    ventas = ventas_de_wow(wow_root)
    if ventas:
        log.info(
            "%s venta(s) apuntadas por Journalator, desde el %s.",
            len(ventas),
            ventas[0].cuando.strftime("%d/%m/%Y"),
        )
    else:
        # Cero ventas puede ser cualquiera de tres cosas muy distintas, y
        # decirlas todas con la misma frase deja al que mira sin saber si tiene
        # que instalar algo, entrar al juego o simplemente esperar.
        _por_que_no_hay_ventas(wow_root)

    subastas = leer_de_wow(wow_root)
    if subastas is None:
        # Nada que sincronizar todavia, pero la maquina esta bien configurada.
        return _solo_ventas(args, ventas)
    log.info("%s subasta(s) tuyas leidas de %s.", len(subastas), wow_root)

    # Sin esto, cada vez que cancelas para repostear el vigilante lo cantaria
    # como una venta: desde la API las dos cosas se ven igual.
    canceladas = leer_canceladas_de_wow(wow_root)
    if canceladas:
        log.info("%s cancelacion(es) apuntadas por el addon.", len(canceladas))

    # /reload solo recarga la sesion en la que lo haces. Con varias cuentas de
    # WoW es facil dejarse una con el addon viejo, y entonces sus reposteos
    # siguen saliendo como ventas sin que nada lo cante.
    # El addon guarda su tabla y una copia en JSON; solo se lee la copia. Si se
    # queda atras, el vigilante lee datos muertos sin enterarse.
    for fichero in encontrar_savedvariables(wow_root):
        atraso = volcado_atrasado(fichero)
        if atraso:
            tabla, volcado = atraso
            log.warning(
                "⚠️  El volcado de %s se ha quedado atras: su tabla es de %s y "
                "lo exportado de %s. Entra con esa cuenta y sal al selector de "
                "personajes para que se ponga al dia.",
                fichero.parts[-3],
                datetime.fromtimestamp(tabla).strftime("%d/%m %H:%M"),
                datetime.fromtimestamp(volcado).strftime("%d/%m %H:%M"),
            )

    viejas = cuentas_con_addon_viejo(wow_root)
    if viejas:
        log.warning(
            "⚠️  Estas cuentas de WoW siguen con el addon viejo y no apuntan tus "
            "cancelaciones: %s. Entra con cada una y haz /reload, o sus "
            "reposteos saldran como ventas.",
            ", ".join(viejas),
        )

    personajes = leer_personajes(wow_root)

    maquina = args.maquina or nombre_de_maquina()
    fichero_subastas = str(Path(args.salida) / f"{maquina}.json")
    fichero_personajes = str(Path(args.personajes) / f"{maquina}.json")
    fichero_ventas = str(Path(args.ventas) / f"{maquina}.json")
    log.info("Escribiendo como maquina %r.", maquina)

    if args.dry_run:
        log.info("--dry-run: no escribo ni subo nada.")
        return EXIT_OK

    cambiados = []
    if escribir_snapshot(fichero_subastas, subastas, canceladas):
        cambiados.append(fichero_subastas)
    if escribir_personajes(fichero_personajes, personajes):
        cambiados.append(fichero_personajes)
    if escribir_resumen(fichero_ventas, ventas):
        cambiados.append(fichero_ventas)

    if not cambiados:
        log.info("Sin cambios respecto a lo ya subido.")
        return EXIT_OK

    log.info("Actualizado: %s.", ", ".join(cambiados))
    return subir(cambiados, push=not args.no_push)


def _por_que_no_hay_ventas(wow_root: Path) -> None:
    """Dice cual de los cuatro motivos es, que piden cosas distintas."""
    if not (wow_root / "Interface" / "AddOns" / "Journalator").is_dir():
        log.info(
            "Journalator no esta instalado. Sin el, el panel de ventas por "
            "reino no cuenta lo que vendas en esta maquina."
        )
        return

    ficheros = encontrar_journalator(wow_root)
    if not ficheros:
        log.warning(
            "⚠️  Journalator esta instalado pero aun no ha guardado nada. WoW "
            "solo escribe los SavedVariables al salir al selector de personajes "
            "o cerrar el juego: entra con cada cuenta y sal al selector."
        )
        return

    apuntes = apuntes_de_wow(wow_root)
    if not apuntes:
        log.warning(
            "⚠️  Journalator ha guardado su fichero en %s cuenta(s), pero esta "
            "vacio. Comprueba que el addon esta activado en la lista de "
            "complementos.",
            len(ficheros),
        )
        return

    log.info(
        "Journalator funciona (%s), pero todavia no ha visto ninguna venta. "
        "Apunta la factura cuando abres el buzon, asi que saldra en cuanto "
        "recojas el correo de la primera venta.",
        ", ".join(f"{n} {seccion}" for seccion, n in sorted(apuntes.items())),
    )


def _solo_ventas(args: argparse.Namespace, ventas) -> int:
    """Sube las ventas cuando el addon de subastas aun no ha volcado nada.

    Son dos addons distintos: que el nuestro este recien instalado no es motivo
    para dejar el panel de ventas sin los meses que Journalator ya lleva
    apuntados.
    """
    if not ventas or args.dry_run:
        return EXIT_OK

    maquina = args.maquina or nombre_de_maquina()
    fichero = str(Path(args.ventas) / f"{maquina}.json")
    if not escribir_resumen(fichero, ventas):
        return EXIT_OK

    log.info("Actualizado: %s.", fichero)
    return subir([fichero], push=not args.no_push)


def firma_de_los_volcados(wow_root: Path) -> tuple:
    """Como estan ahora mismo los ficheros que escribe WoW.

    Fecha y tamano de cada uno. Comparar dos firmas dice si WoW ha guardado algo
    desde la ultima vez que miramos.
    """
    firma = []
    for fichero in encontrar_savedvariables(wow_root):
        try:
            estado = fichero.stat()
        except OSError:
            # Puede desaparecer a media escritura: WoW guarda creando y
            # renombrando. Se recoge en la vuelta siguiente.
            continue
        firma.append((str(fichero), estado.st_mtime_ns, estado.st_size))
    return tuple(firma)


def vigilar(args: argparse.Namespace) -> int:
    """Sincroniza en cuanto WoW guarda los datos del addon.

    WoW escribe los SavedVariables al salir al selector de personajes y al
    cerrar el juego, asi que vigilar esos ficheros es enterarse justo cuando hay
    algo nuevo que subir. Sin esto habria que esperar a la siguiente pasada del
    temporizador, y lo normal es apagar el equipo antes: entonces lo exportado
    se queda sin subir hasta el siguiente encendido, y para cuando sube, las
    subastas ya han caducado y no se puede saber si alguna se vendio.

    En la Steam Deck esto lo hace systemd con una unidad .path. En Windows el
    Programador de tareas no tiene disparador por cambio de fichero, asi que el
    vigilante es este bucle. Mirar unas fechas cada pocos segundos no cuesta
    nada, y se espera a que dejen de cambiar antes de sincronizar porque WoW
    guarda varios ficheros seguidos.
    """
    wow_root = Path(args.wow_root) if args.wow_root else detectar_wow_root()
    if wow_root is None:
        log.error("No encuentro la carpeta de WoW: no hay nada que vigilar.")
        return EXIT_ERROR

    log.info(
        "👀 Vigilando %s. Sincronizare cada vez que salgas al selector de "
        "personajes o cierres el juego. Ctrl+C para parar.",
        wow_root,
    )
    anterior = firma_de_los_volcados(wow_root)
    try:
        while True:
            time.sleep(args.vigilar_cada)
            actual = firma_de_los_volcados(wow_root)
            if actual == anterior:
                continue

            # Esperar a que WoW termine de guardar: si sincronizaramos con la
            # primera senal leeriamos un fichero a medias.
            while True:
                time.sleep(args.vigilar_cada)
                despues = firma_de_los_volcados(wow_root)
                if despues == actual:
                    break
                actual = despues

            anterior = actual
            log.info("💾 WoW ha guardado. Sincronizando.")
            run(args)
    except KeyboardInterrupt:
        log.info("Vigilancia detenida.")
        return EXIT_OK


def registrar_en_fichero(destino: Path, guardar_bytes: int = 512_000) -> None:
    """Ademas de por pantalla, deja el log en un fichero.

    El vigilante corre con pythonw.exe, que no tiene consola: sin esto, todo lo
    que escriba se pierde y una averia no se nota hasta que echas de menos las
    alertas. En la Steam Deck de esto se encarga journalctl; en Windows no hay
    nadie recogiendolo.

    Se recorta por lo bruto al pasar del tamano maximo. Un proceso que vive
    semanas acabaria con un log de cientos de MB, y no merece la pena montar una
    rotacion de verdad para esto.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destino.is_file() and destino.stat().st_size > guardar_bytes:
            cola = destino.read_text(encoding="utf-8", errors="replace")[-guardar_bytes // 2 :]
            destino.write_text(cola, encoding="utf-8")
    except OSError:
        # Un log que no se puede recortar no es motivo para no sincronizar.
        pass

    fichero = logging.FileHandler(destino, encoding="utf-8")
    fichero.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logging.getLogger().addHandler(fichero)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        stream=sys.stdout,
    )
    if args.vigilar:
        registrar_en_fichero(Path(__file__).resolve().parent / ".state" / "sync.log")
    try:
        return vigilar(args) if args.vigilar else run(args)
    except MisSubastasError as exc:
        log.error("%s", exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
