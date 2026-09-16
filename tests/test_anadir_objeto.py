"""Anadir un objeto vigilado desde una issue."""

import pytest

from anadir_objeto import EQUIPO, PATRON, Peticion, id_de, parsear
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
