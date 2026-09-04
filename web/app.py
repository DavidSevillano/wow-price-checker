"""La web pública. Solo lectura: no hay cuentas ni formularios."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.mercado import TIPO_OBJETO
from web.consultas import REINOS_GRATIS, anotar_peticion, ficha, reinos_de
from web.db import RUTA_POR_DEFECTO, abrir

AQUI = Path(__file__).parent


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
