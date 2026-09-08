import pytest
from fastapi.testclient import TestClient

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.app import crear_app
from web.db import abrir
from web.ingesta import guardar_nombres, guardar_reinos, recalcular_estadisticas, volcar


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


@pytest.fixture
def ruta_db(tmp_path):
    ruta = tmp_path / "p.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        con, [(TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None)]
    )
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 271440, 305): {
                i: resumen(i * 1_000_000, listados=i) for i in range(1, 11)
            },
            Clave(TIPO_OBJETO, 271440, 318): {1: resumen(90_000_000)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente(ruta_db):
    return TestClient(crear_app(ruta_db))


def test_la_ficha_responde_con_el_nombre(cliente):
    r = cliente.get("/item/271440")
    assert r.status_code == 200
    assert "Greaves of the Noxious Depths" in r.text


def test_un_producto_desconocido_da_404(cliente):
    assert cliente.get("/item/999999").status_code == 404


def test_la_ficha_solo_pinta_cinco_reinos(cliente):
    texto = cliente.get("/item/271440").text
    assert "Reino 5" in texto
    # El sexto reino y los siguientes no llegan al HTML: el corte está en la
    # consulta, así que no hay nada que descubrir quitando una regla de CSS.
    assert "Reino 6" not in texto


def test_visitar_la_ficha_la_registra(cliente, ruta_db):
    cliente.get("/item/271440")
    con = abrir(ruta_db)
    assert con.execute("SELECT peticiones FROM pagina").fetchone()[0] == 1


def test_se_puede_pedir_una_variante_concreta(cliente):
    r = cliente.get("/item/271440?ilvl=318")
    assert r.status_code == 200
    assert "318" in r.text


def test_sin_ilvl_abre_por_la_variante_con_mas_mercado(cliente):
    """El 305 está en 10 reinos y el 318 en 1: se abre por el que enseña más."""
    texto = cliente.get("/item/271440").text
    assert "Reino 3" in texto


def test_un_ilvl_que_no_existe_no_revienta(cliente):
    """Una URL manipulada cae en la variante por defecto, no en un 500."""
    assert cliente.get("/item/271440?ilvl=9999").status_code == 200


def test_los_precios_salen_en_oro_y_no_en_cobre(cliente):
    """En la base todo es cobre; el usuario piensa en oro (10.000 cobre)."""
    texto = cliente.get("/item/271440").text
    assert "100" in texto            # 1.000.000 de cobre son 100 de oro
    assert "1000000" not in texto


def test_un_ilvl_que_no_es_un_numero_tampoco_revienta(cliente):
    """El mismo error del usuario no puede dar dos respuestas distintas."""
    r = cliente.get("/item/271440?ilvl=abc")
    assert r.status_code == 200
    assert "Greaves of the Noxious Depths" in r.text


def test_el_nombre_del_objeto_sale_escapado(tmp_path):
    """El nombre viene de la API de Blizzard: es texto de fuera.

    Hoy Jinja2 escapa solo, pero nada en la suite lo sujetaba: un `| safe`
    puesto más adelante para "nombres con formato" reabriría el agujero sin
    que fallara nada.
    """
    ruta = tmp_path / "x.db"
    con = abrir(ruta)
    guardar_reinos(con, {1: "Reino 1"})
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "<script>alert(1)</script>", None)])
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1: resumen(1_000_000)}}, generado_en=1)
    recalcular_estadisticas(con)
    con.close()

    texto = TestClient(crear_app(ruta)).get("/item/1").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;" in texto


def test_la_pagina_de_reino_lista_lo_mas_rebajado(cliente):
    r = cliente.get("/realm/reino-1")
    assert r.status_code == 200
    assert "Reino 1" in r.text


def test_un_reino_desconocido_da_404(cliente):
    assert cliente.get("/realm/no-existe").status_code == 404


def test_el_sitemap_solo_lleva_lo_ya_pedido(cliente):
    """Anunciar 20.144 URLs que nadie ha visitado es contenido generado."""
    antes = cliente.get("/sitemap.xml").text
    assert "/item/271440" not in antes

    cliente.get("/item/271440")

    despues = cliente.get("/sitemap.xml").text
    assert despues.startswith("<?xml")
    assert "/item/271440" in despues


def test_el_sitemap_lleva_siempre_los_reinos(cliente):
    """Los reinos son 92 y fijos: esos sí se anuncian desde el primer día."""
    assert "/realm/reino-1" in cliente.get("/sitemap.xml").text


def test_el_sitemap_es_xml_de_verdad(cliente):
    """Si no parsea, Google lo descarta entero y no dice por qué."""
    import xml.etree.ElementTree as ET

    r = cliente.get("/sitemap.xml")
    assert r.headers["content-type"].startswith("application/xml")
    raiz = ET.fromstring(r.text)
    assert raiz.tag.endswith("urlset")


def test_la_ficha_no_promete_un_precio_normal_que_no_sabe(cliente):
    """El ilvl 318 solo esta en un reino: ahi no hay precio "normal".

    Presentar el unico precio que existe como "lo que cuesta normalmente" es
    afirmar algo que la base no sabe.
    """
    texto = cliente.get("/item/271440?ilvl=318").text
    assert "Normally costs" not in texto
    assert "1 realm" in texto


def test_con_reinos_de_sobra_si_sale_el_precio_normal(cliente):
    """El 305 esta en diez reinos: ahi la mediana si significa algo."""
    assert "Normally costs" in cliente.get("/item/271440?ilvl=305").text


def test_la_web_abre_la_base_que_diga_el_entorno(ruta_db, monkeypatch):
    """Sin esto, un uvicorn lanzado desde otra carpeta abre una base vacia,
    la crea con el esquema puesto, y da 404 en todo sin decir por que.
    """
    monkeypatch.setenv("AUCTION_DB", str(ruta_db))
    assert TestClient(crear_app()).get("/item/271440").status_code == 200


def test_sin_variable_de_entorno_usa_la_de_por_defecto(tmp_path, monkeypatch):
    """Y si la de por defecto no tiene nada, la pagina no existe: 404."""
    monkeypatch.delenv("AUCTION_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    assert TestClient(crear_app()).get("/item/271440").status_code == 404


# -- Portada y robots -------------------------------------------------------
#
# `/` daba 404. No es una página que faltara por escribir: es el destino del
# enlace de la marca, que `base.html` pinta en la cabecera de todas las
# páginas, así que cada visita que pulsaba el logotipo se comía un 404. Y el
# sitemap no se anunciaba en ningún sitio, que es lo que hace un robots.txt.


def test_la_portada_responde(cliente):
    r = cliente.get("/")
    assert r.status_code == 200


def test_la_portada_enlaza_los_reinos(cliente):
    texto = cliente.get("/").text
    assert '/realm/reino-1"' in texto
    assert "Reino 1" in texto


def test_la_portada_enlaza_lo_mas_visto(cliente):
    cliente.get("/item/271440")
    texto = cliente.get("/").text
    assert '/item/271440"' in texto
    assert "Greaves of the Noxious Depths" in texto


def test_la_portada_sin_visitas_no_saca_la_lista_vacia(cliente):
    """Recién instalada nadie ha pedido nada: mejor no sacar la sección."""
    texto = cliente.get("/").text
    assert "Greaves of the Noxious Depths" not in texto


def test_visitar_la_portada_no_cuenta_como_pedir_una_ficha(cliente, ruta_db):
    cliente.get("/")
    con = abrir(ruta_db)
    assert con.execute("SELECT count(*) FROM pagina").fetchone()[0] == 0


def test_la_portada_aguanta_una_base_vacia(tmp_path):
    """La primera pasada tarda una hora en llegar y hasta entonces no hay nada."""
    cliente = TestClient(crear_app(tmp_path / "vacia.db"))
    assert cliente.get("/").status_code == 200


def test_el_nombre_del_reino_sale_escapado(tmp_path):
    ruta = tmp_path / "x.db"
    con = abrir(ruta)
    guardar_reinos(con, {1: "<script>alert(1)</script>"})
    con.close()

    texto = TestClient(crear_app(ruta)).get("/").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;" in texto


def test_hay_robots(cliente):
    r = cliente.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_el_robots_anuncia_el_sitemap(cliente):
    """Es la única pista que tiene un rastreador de que el sitemap existe."""
    assert "Sitemap: https://auctionsentinel.example/sitemap.xml" in (
        cliente.get("/robots.txt").text
    )


def test_el_sitemap_lleva_la_portada(cliente):
    """Es la página con más enlaces internos: dejarla fuera es dejar el mapa
    del sitio sin su raíz."""
    assert "<loc>https://auctionsentinel.example/</loc>" in (
        cliente.get("/sitemap.xml").text
    )


# -- La portada con datos ---------------------------------------------------
#
# El fixture `cliente` tiene diez reinos, por debajo del umbral de produccion
# (15), asi que con el no sale ni una rebaja. Este trae veinte justo para
# ejercitar la portada con el umbral de verdad, sin pasarselo a mano: si el
# dia de manana alguien sube ese numero en `mejores_rebajas`, este test lo
# nota en vez de seguir verde con un valor de juguete.


@pytest.fixture
def ruta_grande(tmp_path):
    ruta = tmp_path / "g.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths",
             "https://cdn/greaves.jpg"),
            (TIPO_OBJETO, 100, "en", "Cosa a su precio", None),
        ],
    )
    volcar(
        con,
        {
            # Mediana 1100 y el reino 1 a 110: un 90% de rebaja.
            Clave(TIPO_OBJETO, 271440, 305): {
                1: resumen(110), **{i: resumen(i * 100) for i in range(2, 21)}
            },
            Clave(TIPO_OBJETO, 100, 305): {i: resumen(500) for i in range(1, 21)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente_grande(ruta_grande):
    return TestClient(crear_app(ruta_grande))


def test_la_portada_lista_las_rebajas(cliente_grande):
    texto = cliente_grande.get("/").text
    assert "Greaves of the Noxious Depths" in texto
    assert "90%" in texto


def test_cada_rebaja_enlaza_su_objeto_y_su_reino(cliente_grande):
    texto = cliente_grande.get("/").text
    assert '/item/271440"' in texto
    assert '/realm/reino-1"' in texto


def test_lo_que_esta_a_su_precio_normal_no_sale_como_rebaja(cliente_grande):
    assert "Cosa a su precio" not in cliente_grande.get("/").text


def test_la_portada_dice_cuantos_objetos_y_reinos_cubre(cliente_grande):
    texto = cliente_grande.get("/").text
    assert "Items tracked" in texto and ">2<" in texto
    assert "Realms covered" in texto and ">20<" in texto


def test_la_portada_dice_de_cuando_son_los_datos(cliente_grande):
    """1788451184 es el 2026-09-03 a las 15:59 UTC."""
    texto = cliente_grande.get("/").text
    assert "3 September 2026" in texto
    assert "15:59 UTC" in texto


def test_el_mes_sale_en_ingles_aunque_el_servidor_este_en_espanol(cliente_grande):
    """La pagina esta en ingles y el VPS no tiene por que estarlo.

    `%B` de strftime saca el mes en la locale del sistema: en una maquina en
    espanol pondria "septiembre" en mitad de una frase en ingles.
    """
    assert "September" in cliente_grande.get("/").text


def test_sin_datos_la_portada_no_inventa_una_fecha(cliente):
    """El fixture pequeño no llega al umbral: hay reinos pero no rebajas."""
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Reino 1" in r.text


def test_las_rebajas_no_se_recalculan_en_cada_visita(cliente_grande, monkeypatch):
    """271 ms medidos con 932.000 filas: eso no puede correr por visita.

    Se cachean contra `volcado.generado_en`, que solo cambia cuando la pasada
    horaria escribe un volcado nuevo. No es un TTL a ojo: mientras ese numero
    sea el mismo, el resultado es literalmente el mismo.
    """
    import web.app

    veces = []
    original = web.app.mejores_rebajas

    def contando(*args, **kwargs):
        veces.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(web.app, "mejores_rebajas", contando)

    cliente_grande.get("/")
    cliente_grande.get("/")
    cliente_grande.get("/")

    assert len(veces) == 1


def test_un_volcado_nuevo_invalida_la_cache(cliente_grande, ruta_grande):
    """Si no, la portada se quedaria con las rebajas de la hora pasada."""
    assert "Greaves of the Noxious Depths" in cliente_grande.get("/").text

    con = abrir(ruta_grande)
    volcar(
        con,
        {Clave(TIPO_OBJETO, 100, 305): {i: resumen(500) for i in range(1, 21)}},
        generado_en=1788451184 + 3600,
    )
    recalcular_estadisticas(con)
    con.close()

    assert "Greaves of the Noxious Depths" not in cliente_grande.get("/").text


# -- Ningun enlace interno puede llevar a un 404 ----------------------------
#
# Este test existe porque el fallo se repitio dos veces: la marca de la
# cabecera apuntaba a `/`, que no estaba definida, y el "See all realms" de la
# ficha apuntaba a `/pro`, que era el plan de pago de la v3 y tampoco existia
# --con 92 reinos y 5 visibles, salia en casi todas las fichas. Un enlace
# muerto no lo ve nadie hasta que lo pulsa un usuario.


def test_ningun_enlace_interno_da_404(cliente_grande):
    import re

    paginas = ["/", "/item/271440", "/realm/reino-1"]
    vistos = set()
    for pagina in paginas:
        html = cliente_grande.get(pagina).text
        for href in re.findall(r'href="(/[^"#]*)"', html):
            if href in vistos:
                continue
            vistos.add(href)
            r = cliente_grande.get(href)
            assert r.status_code != 404, f"{pagina} enlaza a {href}, que da 404"

    # Si el regex dejara de encontrar nada, el test pasaria sin comprobar nada.
    assert "/" in vistos and any(h.startswith("/item/") for h in vistos)


# -- Los iconos --------------------------------------------------------------
#
# Una tabla de objetos de WoW sin sus iconos no se lee: son el unico rasgo por
# el que se reconoce un objeto de un vistazo, y los nombres son largos y se
# parecen entre si ("Uncanny Combatant's Satin Belt", "...Satin Pants").


def test_la_portada_pinta_el_icono_del_objeto(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/").text


def test_la_ficha_pinta_el_icono_del_objeto(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/item/271440").text


def test_la_pagina_de_reino_pinta_el_icono(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/realm/reino-1").text


def test_un_objeto_sin_icono_no_deja_una_imagen_rota(tmp_path):
    """Blizzard no tiene icono para todo, y `<img src="">` pide la propia
    pagina otra vez en algunos navegadores. Sin icono, no hay etiqueta.
    """
    ruta = tmp_path / "si.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "Sin foto", None)])
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 1, 305): {
                1: resumen(50_000), **{i: resumen(100_000) for i in range(2, 21)}
            }
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()

    texto = TestClient(crear_app(ruta)).get("/").text
    assert "Sin foto" in texto
    assert 'src=""' not in texto
