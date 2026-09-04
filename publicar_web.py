"""Llena la base de la web publica con el volcado de esta hora.

    py publicar_web.py                      # toda la region
    py publicar_web.py --realms 1305,1329   # dos reinos, para probar
    py publicar_web.py --db /srv/web.db     # otra ruta de base

Va aparte de `main.py` a proposito: main manda tus alertas y no conviene
tocarlo para esto.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from dotenv import load_dotenv

from web.db import RUTA_POR_DEFECTO, abrir
from web.ingesta import guardar_nombres, guardar_reinos, recalcular_estadisticas, volcar
from wowalerts.blizzard import BlizzardClient, BlizzardError
from wowalerts.config import COPPER_PER_GOLD, load_config
from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino, agregar, resumir_reino

log = logging.getLogger("publicar_web")

# Mismo suelo que analizar_mercado.py: por debajo de esto hay decenas de
# miles de objetos de dos cobres que nadie busca jamas, y la region entera no
# cabria en memoria si se guardaran.
PRECIO_MINIMO_ORO = 500

# Los idiomas que sirve la web, guardados con el codigo de dos letras que usa
# `web.consultas.IDIOMA_POR_DEFECTO` y que es la clave `idioma` de la tabla
# `nombre`. Blizzard devuelve doce locales por objeto (verificado contra la
# API), pero tres pares truncan al mismo codigo de dos letras --en_GB/en_US a
# "en", es_ES/es_MX a "es", zh_CN/zh_TW a "zh"--, y guardar los doce pisaria
# una version con la otra segun el orden en que llegue el diccionario de
# Blizzard. Se eligen ocho sin colision: los idiomas nativos de las regiones
# que soporta este proyecto (`wowalerts.config.VALID_REGIONS` = eu/us/kr/tw)
# --ingles para eu y us, coreano para kr, chino para tw-- mas los otros
# cuatro idiomas grandes de la region eu (aleman, frances, italiano, ruso).
# Se deja fuera portugues de Brasil porque no hay ninguna region soportada
# aqui donde sea el idioma nativo. Dentro de cada pareja que colisiona: de
# en_GB/en_US se guarda GB porque "eu" es la region por defecto de
# config.yaml; de es_ES/es_MX se guarda ES, el castellano en el que esta
# escrito este proyecto; de zh_CN/zh_TW se guarda TW, porque es la que
# corresponde a la region "tw" que si se soporta (China no es una region de
# Battle.net aqui).
IDIOMAS = {
    "de_DE": "de",
    "en_GB": "en",
    "es_ES": "es",
    "fr_FR": "fr",
    "it_IT": "it",
    "ko_KR": "ko",
    "ru_RU": "ru",
    "zh_TW": "zh",
}

FilaNombre = tuple[str, int, str, str, str | None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--db", default=str(RUTA_POR_DEFECTO), help="Ruta de la base de la web publica."
    )
    parser.add_argument(
        "--realms",
        default="",
        help="Ids de connected realm separados por comas. Vacio = toda la region.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


# -- descarga -----------------------------------------------------------------


def descargar_reinos(
    client: BlizzardClient, config, realm_ids: Sequence[int], precio_minimo_cobre: int
) -> tuple[list[tuple[int, dict[Clave, ResumenReino]]], dict[int, str]]:
    """Baja, resume y nombra cada reino en paralelo. Mismo patron que
    `analizar_mercado.descargar`: resumir dentro del hilo es lo que hace esto
    viable, porque la region entera no cabe en memoria si se devuelven las
    subastas crudas.

    El nombre del reino se pide en el mismo hilo que sus subastas y no aparte:
    hacen falta los nombres de TODOS los reinos que respondan (la tabla
    `reino` es el indice publico de la web), asi que no hay peticion que
    ahorrar uniendola a la que ya se estaba haciendo.
    """
    resumenes: list[tuple[int, dict[Clave, ResumenReino]]] = []
    nombres_reino: dict[int, str] = {}

    def una(realm_id: int):
        snapshot = client.auctions(realm_id)
        resumen = resumir_reino(
            snapshot.auctions, config.bonus_ilvl_map, precio_minimo_cobre
        )
        nombre = client.connected_realm_name(realm_id)
        return realm_id, resumen, nombre, len(snapshot.auctions)

    with ThreadPoolExecutor(max_workers=config.settings.max_workers) as pool:
        for futuro in [pool.submit(una, r) for r in realm_ids]:
            try:
                realm_id, resumen, nombre, vistas = futuro.result()
            except BlizzardError as exc:
                log.warning("Reino omitido: %s", exc)
                continue
            resumenes.append((realm_id, resumen))
            nombres_reino[realm_id] = nombre
            log.info(
                "  reino %s (%s): %s subastas, %s productos por encima del suelo",
                realm_id,
                nombre,
                vistas,
                len(resumen),
            )

    return resumenes, nombres_reino


def productos_sin_nombre(con, agregado) -> list[tuple[str, int]]:
    """Que (tipo, producto_id) del agregado no tienen fila todavia en `nombre`.

    Los nombres no cambian salvo que Blizzard saque un parche, asi que solo
    hace falta pedirlos la primera vez que aparece un producto: la primera
    pasada pide los ~20 000 objetos que haya en la region, y las siguientes
    casi ninguno. Sin esto, cada pasada horaria repetiria las mismas 20 000
    peticiones que ya se sabian de la pasada anterior.

    Solo entran los objetos (`TIPO_OBJETO`): `item_names` pide por item id, y
    las mascotas no tienen uno propio en las subastas -- todas son la misma
    jaula y lo que las distingue es la especie (ver `wowalerts.mercado`).
    """
    conocidos = {
        (fila[0], fila[1])
        for fila in con.execute("SELECT DISTINCT tipo, producto_id FROM nombre")
    }
    vistos: set[tuple[str, int]] = set()
    faltan: list[tuple[str, int]] = []
    for clave in agregado:
        if clave.tipo != TIPO_OBJETO:
            continue
        par = (clave.tipo, clave.id)
        if par in conocidos or par in vistos:
            continue
        vistos.add(par)
        faltan.append(par)
    return faltan


def pedir_nombres(
    client: BlizzardClient, faltan: Sequence[tuple[str, int]], max_workers: int
) -> list[FilaNombre]:
    """Pide a Blizzard los nombres de lo que falte, en paralelo.

    Incluso en la primera pasada son del orden de 20 000 objetos: en serie
    tardaria decenas de minutos, y el volcado de subastas que se esta
    publicando se renueva cada hora. `client.item_names` ya se traga sus
    propios errores y devuelve {} si un objeto en concreto falla, asi que no
    hace falta capturar nada aqui: un objeto sin nombre esta pasada se vuelve
    a intentar en la siguiente, porque sigue sin tener fila en `nombre`.
    """
    filas: list[FilaNombre] = []

    def uno(par: tuple[str, int]):
        _, producto_id = par
        return producto_id, client.item_names(producto_id)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for futuro in [pool.submit(uno, par) for par in faltan]:
            producto_id, nombres = futuro.result()
            for locale, codigo in IDIOMAS.items():
                nombre = nombres.get(locale)
                if nombre:
                    filas.append((TIPO_OBJETO, producto_id, codigo, nombre, None))

    return filas


# -- orquestacion ---------------------------------------------------------------


def poblar(
    con,
    agregado,
    nombres_reino: dict[int, str],
    nombres_producto: Sequence[FilaNombre],
    generado_en: int,
) -> int:
    """Escribe una pasada entera en la base. Pura: nada de esto toca la red.

    El orden importa: reinos y nombres primero, porque la pagina de producto
    los necesita para renderizar (`web.consultas.ficha` cae a "#id" sin un
    nombre, y `reinos_de` sin un reino no tiene de donde sacar el nombre de
    la fila). Los precios van al final -- `volcar` es lo que se reemplaza
    entero dentro de una transaccion, y es lo que decide que la pasada ha
    terminado de verdad.
    """
    guardar_reinos(con, nombres_reino)
    if nombres_producto:
        guardar_nombres(con, nombres_producto)
    filas = volcar(con, agregado, generado_en)
    recalcular_estadisticas(con)
    return filas


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    load_dotenv()
    config = load_config(args.config)

    client = BlizzardClient(
        os.getenv("BLIZZARD_CLIENT_ID", ""),
        os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )

    realm_ids = (
        [int(r) for r in args.realms.split(",") if r.strip()]
        if args.realms
        else client.connected_realm_ids()
    )

    log.info(
        "Bajando %s reinos (suelo: %s oro)...", len(realm_ids), PRECIO_MINIMO_ORO
    )
    arranque = time.monotonic()
    resumenes, nombres_reino = descargar_reinos(
        client, config, realm_ids, PRECIO_MINIMO_ORO * COPPER_PER_GOLD
    )
    if not resumenes:
        log.error("Ningun reino ha respondido. No se toca la base.")
        return 2
    log.info(
        "%s de %s reinos en %.0f s",
        len(resumenes),
        len(realm_ids),
        time.monotonic() - arranque,
    )

    agregado = agregar(resumenes)
    log.info("%s productos distintos en lo bajado", len(agregado))

    con = abrir(args.db)

    faltan = productos_sin_nombre(con, agregado)
    log.info("%s productos sin nombre todavia", len(faltan))
    arranque_nombres = time.monotonic()
    nombres_producto = pedir_nombres(client, faltan, config.settings.max_workers)
    if faltan:
        log.info(
            "%s filas de nombre en %.0f s",
            len(nombres_producto),
            time.monotonic() - arranque_nombres,
        )

    generado_en = int(time.time())
    filas = poblar(con, agregado, nombres_reino, nombres_producto, generado_en)

    log.info(
        "Listo: %s reinos, %s productos, %s filas de precio, %s productos con "
        "nombre nuevo.",
        len(nombres_reino),
        len(agregado),
        filas,
        len(faltan),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
