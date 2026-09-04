"""La web pública. Solo lectura: no hay cuentas ni formularios."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.mercado import TIPO_OBJETO
from web.consultas import (
    REINOS_GRATIS,
    anotar_peticion,
    ficha,
    paginas_mas_pedidas,
    productos_de_reino,
    reino_por_slug,
    reinos_de,
)
from web.db import RUTA_POR_DEFECTO, abrir

AQUI = Path(__file__).parent

# El sitemap necesita URLs absolutas (Google no las acepta relativas), y el
# dominio real solo se conoce en el servidor -- aquí, en desarrollo y en los
# tests, se usa uno de mentira.
BASE_URL = os.environ.get("BASE_URL", "https://auctionsentinel.example")


def _oro(cobre: int) -> str:
    """Cobre a oro, que es en lo que piensa el jugador.

    La conversión sale de `COPPER_PER_GOLD` y no de un 10000 escrito a mano en
    la plantilla: son el mismo número hoy, pero nada los ataba.
    """
    return f"{cobre // COPPER_PER_GOLD:,}"


def crear_app(ruta_db: Path | str = RUTA_POR_DEFECTO) -> FastAPI:
    """Fabrica la app. Recibe la ruta para que los tests usen su propia base."""
    app = FastAPI(title="Auction Sentinel")
    plantillas = Jinja2Templates(directory=str(AQUI / "plantillas"))
    plantillas.env.filters["oro"] = _oro
    app.mount(
        "/estaticos", StaticFiles(directory=str(AQUI / "estaticos")), name="estaticos"
    )

    # Se abre una vez al arrancar solo para dejar el esquema puesto (las seis
    # CREATE TABLE IF NOT EXISTS más el índice); se cierra enseguida porque no
    # sirve para nada más. Así cada petición puede abrir con esquema=False.
    abrir(ruta_db).close()

    def conexion() -> sqlite3.Connection:
        # Una conexión por petición: SQLite no deja compartirlas entre hilos, y
        # abrir una cuesta ~0,9 ms (medido contra una base de 800.000 filas).
        # El esquema ya está puesto por `crear_app`, así que aquí se salta:
        # volver a comprobarlo en cada petición costaba ~0,15 ms de las
        # ~1,07 ms totales, más que la propia consulta de la página.
        return abrir(ruta_db, esquema=False)

    @app.get("/item/{producto_id}", response_class=HTMLResponse)
    def pagina_producto(
        request: Request, producto_id: int, ilvl: Optional[str] = None
    ):
        con = conexion()
        try:
            datos = ficha(con, TIPO_OBJETO, producto_id)
            if datos is None:
                raise HTTPException(status_code=404, detail="Item not found")

            actual = _variante_pedida(datos["variantes"], ilvl)
            filas = reinos_de(
                con, TIPO_OBJETO, producto_id, actual["variante"],
                limite=REINOS_GRATIS,
            )
            anotar_peticion(con, TIPO_OBJETO, producto_id)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="producto.html",
            context={"ficha": datos, "actual": actual, "reinos": filas},
        )

    @app.get("/realm/{slug}", response_class=HTMLResponse)
    def pagina_reino(request: Request, slug: str):
        con = conexion()
        try:
            reino = reino_por_slug(con, slug)
            if reino is None:
                raise HTTPException(status_code=404, detail="Realm not found")
            filas = productos_de_reino(con, reino["id"], limite=100)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="reino.html",
            context={"reino": reino, "productos": filas},
        )

    @app.get("/sitemap.xml")
    def sitemap():
        """Solo entra lo que ya se ha pedido, más los reinos.

        Anunciar de golpe las 20.144 páginas posibles de producto es el patrón
        que Google trata como contenido generado; en cambio el índice crece
        con la demanda real, página a página, según la deja `anotar_peticion`.
        Los reinos son distintos: son 92, son fijos, y no dependen de que
        nadie los pida --por eso se anuncian todos desde el primer día.
        """
        con = conexion()
        try:
            paginas = paginas_mas_pedidas(con, limite=50_000)
            reinos = [dict(fila) for fila in con.execute("SELECT slug FROM reino")]
        finally:
            con.close()

        urls = [f"{BASE_URL}/item/{p['producto_id']}" for p in paginas]
        urls += [f"{BASE_URL}/realm/{r['slug']}" for r in reinos]

        cuerpo = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
            + "</urlset>"
        )
        # Los datos solo cambian con la pasada horaria, así que una hora de
        # caché no cuesta nada y evita reconstruir un megabyte por cada
        # rastreo: la audiencia entera de esta ruta son crawlers que vuelven.
        return Response(
            content=cuerpo,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    return app


def _variante_pedida(variantes: list[dict], ilvl: Optional[str]) -> dict:
    """La variante pedida, o la que más reinos tiene si no se pidió ninguna.

    El ilvl llega como texto y se convierte aquí a propósito. Si se tipara como
    int, un `?ilvl=abc` daría el 422 en JSON de FastAPI en una página que
    Google rastrea, mientras que un `?ilvl=9999` --el mismo error del
    usuario-- cae con elegancia en la variante por defecto. Un solo camino.

    La más extendida y no la primera: en las Grebas, el ilvl 318 solo está en
    12 reinos y el 305 en 85, así que abrir por el 305 enseña más mercado.
    """
    if ilvl is not None:
        try:
            pedido = int(ilvl)
        except (TypeError, ValueError):
            pedido = None
        if pedido is not None:
            for v in variantes:
                if v["variante"] == pedido:
                    return v
    return max(variantes, key=lambda v: v["reinos"])


app = crear_app()
