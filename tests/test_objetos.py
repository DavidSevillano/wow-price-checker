"""Anadir un objeto nuevo al texto de config.yaml."""

import pytest
import yaml

from wowalerts.objetos import ObjetoError, anadir_equipo, anadir_patron, tabla_de
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


def test_un_comentario_que_menciona_max_price_by_ilvl_no_engana_a_tabla_de():
    """La subcadena puede aparecer en un comentario sin ser la clave de verdad."""
    texto = CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"\n',
        '  - name: "Pattern: Arcanoweave Cord"\n'
        "    # ver max_price_by_ilvl { } en otra pieza\n",
    )
    with pytest.raises(ObjetoError, match="precio unico"):
        tabla_de(texto, "Pattern: Arcanoweave Cord")


def test_el_equipo_nuevo_va_detras_del_objeto_del_que_copia():
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, "Temple Delver's Mystic Helm")

    assert nuevo == CONFIG.replace(
        '  - name: "Greaves of the Noxious Depths"',
        '  - name: "Venom Rite Mantle"\n'
        "    item_id: 123456\n"
        "    max_price_by_ilvl:\n"
        "      { 295: 9000, 298: 12000, 311: 90000 }\n"
        "\n"
        '  - name: "Greaves of the Noxious Depths"',
    )


def test_el_resto_del_fichero_no_se_toca():
    """Lo unico que cambia es el bloque nuevo: comentarios y todo lo demas, igual."""
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, "Temple Delver's Mystic Helm")

    sin_lo_nuevo = nuevo.replace(
        '  - name: "Venom Rite Mantle"\n'
        "    item_id: 123456\n"
        "    max_price_by_ilvl:\n"
        "      { 295: 9000, 298: 12000, 311: 90000 }\n"
        "\n",
        "",
    )
    assert sin_lo_nuevo == CONFIG


def test_un_nombre_con_comillas_dobles_se_rechaza():
    """topes.py no sabe buscar un nombre con comillas escapadas, asi que nunca
    se podria cambiar su tope despues. Mejor no dejarlo entrar."""
    with pytest.raises(ObjetoError, match="comillas dobles"):
        anadir_equipo(CONFIG, 'Bolt of "Silk"', 1, "Temple Delver's Mystic Helm")


def test_un_nombre_con_apostrofo_y_dos_puntos_se_lee_bien_con_yaml():
    """Un nombre normal, con los caracteres que dan problemas sin comillas,
    tiene que salir entrecomillado y el YAML resultante tiene que cargarlo tal
    cual se pidio."""
    nuevo = anadir_equipo(CONFIG, "Pattern: Kael'thas's Cord", 1, "Temple Delver's Mystic Helm")

    datos = yaml.safe_load(nuevo)
    nombres = [item["name"] for item in datos["items"]]
    assert "Pattern: Kael'thas's Cord" in nombres


def test_copiar_de_un_objeto_que_no_existe_se_explica():
    with pytest.raises(TopeError, match="No encuentro"):
        anadir_equipo(CONFIG, "Venom Rite Mantle", 1, "Molten Helm")


def test_el_comentario_que_abre_la_seccion_siguiente_se_queda_debajo():
    """config.yaml tiene comentarios entre objetos que abren otra seccion
    ('Monturas caras'). Son de lo de detras, asi que lo nuevo va delante."""
    texto = CONFIG.replace(
        '  - name: "Greaves of the Noxious Depths"',
        "  # --- Piezas de la banda\n"
        '  - name: "Greaves of the Noxious Depths"',
    )
    nuevo = anadir_equipo(texto, "Venom Rite Mantle", 123456, "Temple Delver's Mystic Helm")

    assert (
        "      { 295: 9000, 298: 12000, 311: 90000 }\n"
        "\n"
        '  - name: "Venom Rite Mantle"\n'
        "    item_id: 123456\n"
        "    max_price_by_ilvl:\n"
        "      { 295: 9000, 298: 12000, 311: 90000 }\n"
        "\n"
        "  # --- Piezas de la banda\n"
    ) in nuevo


def test_el_patron_va_detras_del_ultimo_reposteable():
    """Detras del ultimo 'repostear: true', no al final: las monturas van aparte."""
    nuevo = anadir_patron(CONFIG, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == CONFIG.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )


def test_sin_ningun_reposteable_va_detras_del_ultimo_objeto():
    texto = CONFIG.replace("    repostear: true\n", "")
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    esperado = (
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    # Detras del ultimo objeto, que es la montura, y delante de lo que sigue.
    assert esperado + "\norden_personajes:" in nuevo


def test_el_patron_no_se_mete_debajo_del_comentario_de_las_monturas():
    texto = CONFIG.replace(
        '  - name: "Wooly White Rhino"',
        "  # --- Monturas caras\n"
        '  - name: "Wooly White Rhino"',
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert (
        "    repostear: true\n"
        "\n"
        "  # --- Monturas caras\n"
        '  - name: "Wooly White Rhino"'
    ) in nuevo
    assert nuevo.index("Pattern: Lo Que Sea") < nuevo.index("# --- Monturas caras")


def test_el_patron_se_anade_al_final_cuando_no_hay_nada_detras():
    """El fichero puede acabar en el ultimo objeto, sin linea en blanco.

    Sin reposteables, para que el sitio sea detras de la montura, que es lo
    ultimo del fichero.
    """
    texto = CONFIG.split("orden_personajes:")[0].rstrip() + "\n"
    texto = texto.replace("    repostear: true\n", "")
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo.endswith(
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    assert nuevo.startswith(texto.rstrip("\n") + "\n\n")


def test_el_patron_se_coloca_bien_si_el_reposteable_anterior_tiene_comentario_en_el_nombre():
    """La linea 'name:' del reposteable lleva un comentario detras. No hay que
    reconstruir el nombre a partir de ahi para volver a buscarlo."""
    texto = CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"',
        '  - name: "Pattern: Arcanoweave Cord"  # nota',
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == texto.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )


def test_repostear_true_con_comentario_detras_cuenta_igual():
    texto = CONFIG.replace(
        "    repostear: true\n",
        "    repostear: true  # nota\n",
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == texto.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )
