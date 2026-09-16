"""Anadir un objeto nuevo al texto de config.yaml."""

import pytest

from wowalerts.objetos import ObjetoError, tabla_de
from wowalerts.topes import TopeError

CONFIG = """\
region: eu

items:
  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 311: 90000 }

  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl:
      { 295: 6999, 298: 12000,
        311: 90000 }

  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false
    repostear: true

  - name: "Wooly White Rhino"
    item_id: 54068
    max_price: 200000
    avisar_undercut: false

orden_personajes:
  - Adannor

bonus_ilvl_map:
  12843: 311
"""


def test_la_tabla_sale_tal_cual_esta_escrita():
    assert tabla_de(CONFIG, "Temple Delver's Mystic Helm") == (
        "    max_price_by_ilvl:\n"
        "      { 295: 9000, 298: 12000, 311: 90000 }\n"
    )


def test_una_tabla_de_varias_lineas_sale_entera():
    assert tabla_de(CONFIG, "Greaves of the Noxious Depths") == (
        "    max_price_by_ilvl:\n"
        "      { 295: 6999, 298: 12000,\n"
        "        311: 90000 }\n"
    )


def test_un_objeto_de_precio_unico_no_tiene_tabla_que_copiar():
    with pytest.raises(ObjetoError, match="precio unico"):
        tabla_de(CONFIG, "Pattern: Arcanoweave Cord")


def test_un_objeto_que_no_existe_se_explica():
    with pytest.raises(TopeError, match="No encuentro"):
        tabla_de(CONFIG, "Molten Helm")
