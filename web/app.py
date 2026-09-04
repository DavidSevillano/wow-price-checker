"""La web pública. Solo lectura: no hay cuentas ni formularios."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wowalerts.mercado import TIPO_OBJETO
from web.consultas import REINOS_GRATIS, anotar_peticion, ficha, reinos_de
from web.db import RUTA_POR_DEFECTO, abrir

AQUI = Path(__file__).parent


def crear_app(ruta_db: Path | str = RUTA_POR_DEFECTO) -> FastAPI:
    """Fabrica la app. Recibe la ruta para que los tests usen su propia base."""
    app = FastAPI(title="Auction Sentinel")
    plantillas = Jinja2Templates(directory=str(AQUI / "plantillas"))
    app.mount(
        "/estaticos", StaticFiles(directory=str(AQUI / "estaticos")), name="estaticos"
    )

    def conexion() -> sqlite3.Connection:
        # Una conexión por petición: SQLite no deja compartirlas entre hilos, y
        # abrir una cuesta microsegundos.
        return abrir(ruta_db)

    @app.get("/item/{producto_id}", response_class=HTMLResponse)
    def pagina_producto(
        request: Request, producto_id: int, ilvl: Optional[int] = None
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


def _variante_pedida(variantes: list[dict], ilvl: Optional[int]) -> dict:
    """La variante pedida, o la que más reinos tiene si no se pidió ninguna.

    La más extendida y no la primera: en las Grebas, el ilvl 318 solo está en
    12 reinos y el 305 en 85, así que abrir por el 305 enseña más mercado.
    """
    if ilvl is not None:
        for v in variantes:
            if v["variante"] == ilvl:
                return v
    return max(variantes, key=lambda v: v["reinos"])


def __getattr__(name: str):
    """`app` perezoso, para servir con `uvicorn web.app:app`.

    Si `app = crear_app()` estuviera a nivel de módulo, el mero
    `from web.app import crear_app` de los tests ya ejecutaría `abrir()`
    sobre `RUTA_POR_DEFECTO` ("web.db") como efecto colateral de importar el
    módulo, dejando una base suelta en el directorio de trabajo cada vez que
    se recolectan los tests. Con `__getattr__` (PEP 562) esa construcción
    solo ocurre cuando alguien pide `web.app.app` de verdad -- uvicorn, no
    pytest -- y el resultado se cachea en el módulo para no reabrir la base
    en cada acceso posterior.
    """
    if name == "app":
        app = crear_app()
        globals()["app"] = app
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
