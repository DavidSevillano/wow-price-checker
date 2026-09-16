"""Anadir un objeto vigilado desde una issue."""

import pytest

from anadir_objeto import (
    EQUIPO,
    PATRON,
    Peticion,
    comprobar_nuevo,
    id_de,
    parsear,
    resolver,
    verificar,
)
from wowalerts.blizzard import BlizzardAuthError
from wowalerts.config import ItemRule, load_config
from wowalerts.objetos import ObjetoError

# Lo que genera el formulario de GitHub, y lo que copia la app.
EQUIPO_NUEVO = """\
### Objeto

https://www.wowhead.com/es/item=123456/venom-rite-mantle

### Tipo

Equipo (tabla por ilvl)

### Copiar topes de

Temple Delver's Mystic Helm

### Tope, en oro

_No response_
"""

PATRON_NUEVO = """\
### Objeto

Pattern: Lo Que Sea

### Tipo

Patrón o receta (precio unico)

### Copiar topes de

_No response_

### Tope, en oro

40000
"""


def test_una_pieza_de_equipo():
    assert parsear(EQUIPO_NUEVO) == Peticion(
        objeto="https://www.wowhead.com/es/item=123456/venom-rite-mantle",
        tipo=EQUIPO,
        copiar_de="Temple Delver's Mystic Helm",
        tope=None,
    )


def test_un_patron():
    assert parsear(PATRON_NUEVO) == Peticion(
        objeto="Pattern: Lo Que Sea",
        tipo=PATRON,
        copiar_de=None,
        tope=40000,
    )


def test_el_tipo_se_reconoce_con_y_sin_tilde():
    """El desplegable lo escribe un humano en el YAML; la tilde no debe romperlo."""
    sin_tilde = PATRON_NUEVO.replace("Patrón", "Patron")
    assert parsear(sin_tilde).tipo == PATRON


def test_el_tope_admite_separadores_de_miles():
    assert parsear(PATRON_NUEVO.replace("\n40000\n", "\n40.000 g\n")).tope == 40000


def test_una_pieza_de_equipo_sin_de_donde_copiar():
    cuerpo = EQUIPO_NUEVO.replace("Temple Delver's Mystic Helm", "_No response_")
    with pytest.raises(ObjetoError, match="Copiar topes de"):
        parsear(cuerpo)


def test_un_patron_sin_precio():
    cuerpo = PATRON_NUEVO.replace("\n40000\n", "\n_No response_\n")
    with pytest.raises(ObjetoError, match="Tope, en oro"):
        parsear(cuerpo)


def test_un_tipo_que_no_es_ninguno_de_los_dos():
    cuerpo = PATRON_NUEVO.replace("Patrón o receta (precio unico)", "Mascota")
    with pytest.raises(ObjetoError, match="tipo"):
        parsear(cuerpo)


def test_falta_un_campo():
    with pytest.raises(ObjetoError, match="Tipo"):
        parsear(EQUIPO_NUEVO.split("### Tipo")[0])


def test_el_id_sale_del_enlace_de_wowhead():
    assert id_de("https://www.wowhead.com/item=258126") == 258126
    assert id_de("https://www.wowhead.com/es/item=258126/patron-lo-que-sea") == 258126


def test_el_id_sale_de_un_numero_suelto():
    assert id_de(" 258126 ") == 258126


def test_un_nombre_no_lleva_id_dentro():
    assert id_de("Pattern: Arcanoweave Cord") is None


def test_un_digito_no_ascii_no_cuela():
    """'²'.isdigit() da True, pero int('²') no funciona: no es un id valido."""
    assert id_de("²") is None


def test_el_id_sale_de_un_enlace_con_query_string():
    assert id_de("https://www.wowhead.com/?item=258126") == 258126


def test_el_cuerpo_admite_saltos_de_linea_crlf():
    assert parsear(EQUIPO_NUEVO.replace("\n", "\r\n")) == parsear(EQUIPO_NUEVO)


class ClienteFalso:
    """Blizzard sin red: lo que sabe esta en los dos diccionarios."""

    # Un token cualquiera: basta con que acceder a el no explote.
    token = "token-de-prueba"

    def __init__(self, por_id=None, por_nombre=None):
        self.por_id = por_id or {}
        self.por_nombre = por_nombre or {}

    def item_name(self, item_id):
        return self.por_id.get(item_id)

    def search_item_id(self, nombre):
        return self.por_nombre.get(nombre)


class ClienteFalsoSinCredenciales:
    """Simula que Blizzard rechaza las credenciales al pedir el token."""

    @property
    def token(self):
        raise BlizzardAuthError("Blizzard rechaza las credenciales.")


def test_un_enlace_se_resuelve_por_id():
    cliente = ClienteFalso(por_id={123456: "Venom Rite Mantle"})

    assert resolver(cliente, parsear(EQUIPO_NUEVO)) == ("Venom Rite Mantle", 123456)


def test_un_nombre_se_resuelve_por_busqueda():
    cliente = ClienteFalso(por_nombre={"Pattern: Lo Que Sea": 999})

    assert resolver(cliente, parsear(PATRON_NUEVO)) == ("Pattern: Lo Que Sea", 999)


def test_el_nombre_resuelto_es_el_canonico_de_blizzard():
    """Buscado por nombre, se guarda el nombre exacto que devuelve Blizzard."""
    cliente = ClienteFalso(
        por_nombre={"pattern: lo que sea": 999},
        por_id={999: "Pattern: Lo Que Sea"},
    )
    peticion = Peticion(
        objeto="pattern: lo que sea", tipo=PATRON, copiar_de=None, tope=40000
    )

    assert resolver(cliente, peticion) == ("Pattern: Lo Que Sea", 999)


def test_un_id_que_blizzard_no_conoce():
    with pytest.raises(ObjetoError, match="123456"):
        resolver(ClienteFalso(), parsear(EQUIPO_NUEVO))


def test_un_nombre_que_blizzard_no_encuentra():
    with pytest.raises(ObjetoError, match="ingles"):
        resolver(ClienteFalso(), parsear(PATRON_NUEVO))


def test_un_objeto_ya_vigilado_por_nombre():
    config = _config_con(ItemRule(name="Venom Rite Mantle", max_price=100))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 123456)


def test_un_objeto_ya_vigilado_por_id():
    config = _config_con(ItemRule(name="Otro nombre", max_price=100, item_id=123456))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 123456)


def test_un_objeto_ya_vigilado_con_otras_mayusculas():
    config = _config_con(ItemRule(name="venom rite mantle", max_price=100))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 999)


def _config_con(*reglas):
    from wowalerts.config import Config, Settings

    return Config(region="eu", items=reglas, bonus_ilvl_map={}, settings=Settings())


CONFIG = """\
region: eu

items:
  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 311: 90000 }

  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false
    repostear: true

bonus_ilvl_map:
  12843: 311
"""


def test_verificar_acepta_una_pieza_copiada():
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.copiar_de)

    regla = verificar(CONFIG, nuevo, "Venom Rite Mantle", 123456, peticion)

    assert dict(regla.max_price_by_ilvl) == {295: 9000, 298: 12000, 311: 90000}


def test_verificar_caza_una_edicion_que_toca_otro_objeto():
    """La red de seguridad: si se ha movido algo mas, no se commitea."""
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.copiar_de)
    corrupto = nuevo.replace("max_price: 60000", "max_price: 1")

    with pytest.raises(ObjetoError, match="otros objetos"):
        verificar(CONFIG, corrupto, "Venom Rite Mantle", 123456, peticion)


def test_verificar_caza_una_edicion_que_anade_otro_objeto_mas():
    """La red de seguridad: si se ha colado un objeto extra, no se commitea."""
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.copiar_de)
    corrupto = nuevo.replace(
        "bonus_ilvl_map:",
        '  - name: "Extra Objeto"\n    max_price: 10\n\nbonus_ilvl_map:',
    )

    with pytest.raises(ObjetoError, match="anadido"):
        verificar(CONFIG, corrupto, "Venom Rite Mantle", 123456, peticion)


def test_verificar_caza_un_yaml_roto():
    peticion = parsear(EQUIPO_NUEVO)
    roto = CONFIG + '  - name: "Venom Rite Mantle"\n    max_price_by_ilvl:\n      { 295:\n'

    with pytest.raises(ObjetoError, match="no es valido"):
        verificar(CONFIG, roto, "Venom Rite Mantle", 123456, peticion)


def test_el_comentario_de_exito(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_id={123456: "Venom Rite Mantle"}),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "Objeto anadido" in salida
    assert "Venom Rite Mantle" in salida
    assert "id 123456" in salida
    # Separador de miles a la espanola.
    assert "ilvl 311: 90.000" in salida
    assert '"Venom Rite Mantle"' in ruta.read_text(encoding="utf-8")


def test_un_fallo_no_escribe_nada_y_sale_con_error(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(anadir_objeto, "BlizzardClient", lambda **kw: ClienteFalso())

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def test_credenciales_invalidas_no_se_confunden_con_un_id_desconocido(
    tmp_path, capsys, monkeypatch
):
    """Si Blizzard rechaza las credenciales, que se note y no que "no conoce el id"."""
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalsoSinCredenciales(),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def _explota(*args, **kwargs):
    raise RuntimeError("boom")


def test_un_fallo_inesperado_tampoco_se_queda_sin_comentario(
    tmp_path, capsys, monkeypatch
):
    """El workflow publica el stdout como comentario: uno vacio no sirve."""
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_id={123456: "Venom Rite Mantle"}),
    )
    monkeypatch.setattr(anadir_objeto, "resolver", _explota)

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def test_un_patron_sale_con_sus_banderas(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PATRON_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_nombre={"Pattern: Lo Que Sea": 999}),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 0

    escrito = load_config(ruta)
    regla = next(r for r in escrito.items if r.name == "Pattern: Lo Que Sea")
    assert regla.max_price == 40000
    assert regla.avisar_undercut is False
    assert regla.se_repostea is True
