from pathlib import Path

from wowalerts.blizzard import AuctionSnapshot, BlizzardError
from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino
from web.consultas import ficha
from web.db import abrir
from web.ingesta import guardar_nombres

from publicar_web import EXIT_DEMASIADOS_FALLOS, EXIT_OK, main, poblar, productos_sin_nombre

# Directorio del repositorio: hace falta para que `--config config.yaml` (la
# ruta relativa por defecto de `main()`) encuentre el fichero de verdad, sin
# depender de con que cwd haya arrancado pytest.
RAIZ = Path(__file__).resolve().parent.parent


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


def test_poblar_deja_precios_estadisticas_nombres_y_reinos(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_OBJETO, 271440, 305): {
            1305: resumen(500_000_000),
            1329: resumen(700_000_000),
        }
    }
    nombres_reino = {1305: "Kazzak", 1329: "Zul'jin / Uldum"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
        (TIPO_OBJETO, 271440, "es", "Grebas de las profundidades nocivas", None),
    ]

    filas = poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1788451184)

    assert filas == 2
    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM estadistica").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 2
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 1788451184


def test_poblar_dos_veces_no_duplica(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 1, 305): {1305: resumen(100)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [(TIPO_OBJETO, 1, "en", "Algo", None)]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)
    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=2)

    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 1
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 2


def test_solo_se_piden_los_nombres_que_faltan(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(con, [(TIPO_OBJETO, 111, "en", "Ya tengo nombre", None)])

    agregado = {
        Clave(TIPO_OBJETO, 111, 305): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 222, 305): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 222)]


def test_las_mascotas_no_piden_nombre(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_MASCOTA, 303, 3): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 111, None): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 111)]


def test_el_idioma_guardado_es_el_que_consulta_la_web(tmp_path):
    """Si el codigo de idioma no coincide con lo que consulta la web, la ficha
    cae al `#id` de repuesto en vez de ensenar el nombre de verdad -- esto es
    lo unico que demuestra que ingesta y web estan de acuerdo en el idioma.
    """
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
    ]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)

    resultado = ficha(con, TIPO_OBJETO, 271440)
    assert resultado["nombre"] == "Greaves of the Noxious Depths"
    assert resultado["nombre"] != "#271440"


class ClientePrueba:
    """Cliente falso, sin red: los reinos de `fallan` lanzan `BlizzardError`
    al pedir sus subastas (como haria un reino caido de verdad), y el resto
    responde con una subasta del mismo objeto por encima del suelo de precio.
    """

    def __init__(self, fallan):
        self.fallan = set(fallan)

    def auctions(self, realm_id):
        if realm_id in self.fallan:
            raise BlizzardError("simulado: reino caido")
        return AuctionSnapshot(
            auctions=[{"item": {"id": 271440}, "buyout": 500_000_000, "quantity": 1}],
            taken_at=None,
        )

    def connected_realm_name(self, realm_id):
        return f"Reino {realm_id}"

    def item_names(self, item_id):
        return {"en_GB": f"Objeto {item_id}"}


def _snapshot(db_path):
    """Contenido de las tablas que `main()` puede tocar, para comparar antes y
    despues de una pasada."""
    con = abrir(db_path)
    try:
        return {
            "precio": con.execute(
                "SELECT * FROM precio ORDER BY tipo, producto_id, variante, reino_id"
            ).fetchall(),
            "reino": con.execute("SELECT * FROM reino ORDER BY id").fetchall(),
            "nombre": con.execute(
                "SELECT * FROM nombre ORDER BY tipo, producto_id, idioma"
            ).fetchall(),
            "volcado": con.execute("SELECT * FROM volcado").fetchall(),
        }
    finally:
        con.close()


def test_si_fallan_demasiados_reinos_no_se_toca_la_base(tmp_path, monkeypatch):
    """Por encima del umbral (30%), `main()` no debe escribir nada: los datos
    de la pasada anterior tienen como mucho una hora, mientras que publicar
    solo lo que ha respondido borraria de la web los reinos que han fallado
    -- eso es peor que no publicar.
    """
    monkeypatch.chdir(RAIZ)
    db_path = tmp_path / "web.db"

    # Pasada buena conocida, para comprobar despues que sobrevive intacta.
    con = abrir(db_path)
    agregado = {Clave(TIPO_OBJETO, 271440, None): {1305: resumen(500_000_000)}}
    poblar(
        con,
        agregado,
        {1305: "Kazzak"},
        [(TIPO_OBJETO, 271440, "en", "Algo", None)],
        generado_en=1000,
    )
    con.close()
    antes = _snapshot(db_path)

    realm_ids = list(range(1, 11))
    fallan = realm_ids[:6]  # 6 de 10 = 60% > 30%: por encima del umbral.
    cliente = ClientePrueba(fallan=fallan)

    codigo = main(
        [
            "--realms", ",".join(map(str, realm_ids)),
            "--db", str(db_path),
            "--config", "config.yaml",
        ],
        client=cliente,
    )

    assert codigo == EXIT_DEMASIADOS_FALLOS
    assert _snapshot(db_path) == antes


def test_si_fallan_pocos_reinos_se_publica_igual(tmp_path, monkeypatch):
    """Por debajo del umbral, un par de reinos caidos no debe frenar la
    publicacion del resto: es el caso normal que el umbral tiene que dejar
    pasar sin tocar el codigo de salida ni saltarse la base.
    """
    monkeypatch.chdir(RAIZ)
    db_path = tmp_path / "web.db"

    realm_ids = list(range(1, 11))
    fallan = realm_ids[:2]  # 2 de 10 = 20% <= 30%: por debajo del umbral.
    cliente = ClientePrueba(fallan=fallan)

    codigo = main(
        [
            "--realms", ",".join(map(str, realm_ids)),
            "--db", str(db_path),
            "--config", "config.yaml",
        ],
        client=cliente,
    )

    assert codigo == EXIT_OK
    con = abrir(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 8
        assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 8
    finally:
        con.close()
