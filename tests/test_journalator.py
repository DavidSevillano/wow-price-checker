"""Pruebas del lector del addon Journalator.

El formato no es nuestro: lo fijan LibSerialize y LibDeflate. Aqui se comprueba
que lo entendemos igual que ellos, empezando por bloques hechos a mano con las
mismas reglas y acabando en las ventas que salen del fichero entero.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timezone

import pytest

from wowalerts.journalator import (
    ALFABETO,
    JournalatorError,
    Venta,
    bloques,
    descodifica_impresion,
    deserializa,
    escribir_resumen,
    leer_resumenes,
    ranking,
    resumir,
    ventas_de_texto,
)


# -- Codificacion a 6 bits ---------------------------------------------------


def codifica_impresion(datos: bytes) -> str:
    """EncodeForPrint, para poder ir y volver en las pruebas."""
    acumulado = bits = 0
    salida = []
    for byte in datos:
        acumulado |= byte << bits
        bits += 8
        while bits >= 6:
            salida.append(ALFABETO[acumulado & 0x3F])
            acumulado >>= 6
            bits -= 6
    if bits:
        salida.append(ALFABETO[acumulado & 0x3F])
    return "".join(salida)


@pytest.mark.parametrize(
    "datos",
    [b"", b"a", b"ab", b"abc", b"abcd", bytes(range(256)), b"\x00\x00\x00"],
)
def test_ida_y_vuelta_de_la_codificacion(datos):
    assert descodifica_impresion(codifica_impresion(datos)) == datos


def test_un_caracter_de_fuera_del_alfabeto_se_canta():
    with pytest.raises(JournalatorError, match="EncodeForPrint"):
        descodifica_impresion("abc*def")


# -- LibSerialize ------------------------------------------------------------

CABECERA = bytes([1])  # version del formato


def test_entero_pequeño_va_en_la_propia_cabecera():
    # NNNNNNN1: el 7 se escribe como 7*2+1.
    assert deserializa(CABECERA + bytes([7 * 2 + 1])) == 7


def test_entero_de_doce_bits():
    # NNNN S100 mas un byte: 300 = (300*16+4) repartido en dos bytes.
    empaquetado = 300 * 16 + 4
    datos = CABECERA + bytes([empaquetado % 256, empaquetado // 256])
    assert deserializa(datos) == 300


def test_entero_de_doce_bits_negativo():
    empaquetado = 300 * 16 + 12
    datos = CABECERA + bytes([empaquetado % 256, empaquetado // 256])
    assert deserializa(datos) == -300


def test_entero_grande_va_en_big_endian():
    # NUM_32_POS = tipo 5, cabecera 5*8.
    assert deserializa(CABECERA + bytes([5 * 8]) + (123456).to_bytes(4, "big")) == 123456


def test_los_negativos_llevan_su_propio_tipo():
    # NUM_16_NEG = tipo 2.
    assert deserializa(CABECERA + bytes([2 * 8]) + (700).to_bytes(2, "big")) == -700


def test_float():
    # NUM_FLOAT = tipo 9, ocho bytes IEEE754.
    datos = CABECERA + bytes([9 * 8]) + struct.pack(">d", 1.5)
    assert deserializa(datos) == 1.5


def test_numero_guardado_como_texto():
    # NUM_FLOATSTR_POS = tipo 10: un byte de largo y el numero escrito.
    datos = CABECERA + bytes([10 * 8, 4]) + b"2.75"
    assert deserializa(datos) == 2.75


def test_nil_y_booleanos():
    assert deserializa(CABECERA + bytes([0])) is None
    assert deserializa(CABECERA + bytes([12 * 8])) is True
    assert deserializa(CABECERA + bytes([13 * 8])) is False


def cadena_corta(texto: bytes) -> bytes:
    """CCCCTT10 con tipo 0 (cadena) y el largo metido en la cabecera."""
    return bytes([((len(texto) << 2) << 2) | 2]) + texto


def test_cadena_con_el_largo_en_la_cabecera():
    assert deserializa(CABECERA + cadena_corta(b"hola")) == "hola"


def test_cadena_larga_lleva_su_largo_aparte():
    # STR_8 = tipo 14.
    texto = b"x" * 200
    datos = CABECERA + bytes([14 * 8, 200]) + texto
    assert deserializa(datos) == "x" * 200


def test_lista_con_la_cuenta_en_la_cabecera():
    # tipo 2 (lista) con dos elementos.
    datos = CABECERA + bytes([(2 << 4) | (2 << 2) | 2, 1 * 2 + 1, 2 * 2 + 1])
    assert deserializa(datos) == [1, 2]


def test_tabla_con_la_cuenta_en_la_cabecera():
    # tipo 1 (tabla) con una pareja clave/valor.
    datos = CABECERA + bytes([(1 << 4) | (1 << 2) | 2]) + cadena_corta(b"a") + bytes([9])
    assert deserializa(datos) == {"a": 4}


def test_una_cadena_repetida_se_guarda_una_vez():
    """Las de mas de dos bytes se numeran y luego se referencian."""
    # Tabla de dos parejas: {"hola": "hola"} donde el valor es la referencia 1.
    # STRINGREF_8 = tipo 26.
    datos = (
        CABECERA
        + bytes([(1 << 4) | (1 << 2) | 2])
        + cadena_corta(b"hola")
        + bytes([26 * 8, 1])
    )
    assert deserializa(datos) == {"hola": "hola"}


def test_una_referencia_que_no_existe_se_canta():
    with pytest.raises(JournalatorError, match="repetida"):
        deserializa(CABECERA + bytes([26 * 8, 9]))


def test_un_bloque_cortado_se_canta():
    with pytest.raises(JournalatorError, match="se corta"):
        deserializa(CABECERA + bytes([14 * 8, 200]) + b"solo unos pocos")


def test_una_version_mas_nueva_se_canta():
    with pytest.raises(JournalatorError, match="version"):
        deserializa(bytes([99, 1]))


def test_una_tabla_mixta_junta_lista_y_parejas():
    # tipo 3 (mixta): los cuatro bits son dos cuentas de dos, cada una una
    # unidad menos de lo que vale. Aqui 1 de lista y 1 de tabla: c = 0.
    datos = (
        CABECERA
        + bytes([(0 << 4) | (3 << 2) | 2])
        + bytes([7 * 2 + 1])
        + cadena_corta(b"a")
        + bytes([9])
    )
    assert deserializa(datos) == {1: 7, "a": 4}


# -- Del fichero de WoW a las ventas -----------------------------------------


def bloque_de(valor) -> str:
    """Empaqueta un valor como lo haria Archivist al guardar."""
    return codifica_impresion(zlib.compress(_serializa(valor), 9)[2:-4])


def _serializa(valor) -> bytes:
    """Un serializador minimo, suficiente para lo que usan las pruebas."""

    def uno(v) -> bytes:
        if v is None:
            return bytes([0])
        if isinstance(v, bool):
            return bytes([(12 if v else 13) * 8])
        if isinstance(v, int):
            if 0 <= v <= 127:
                return bytes([v * 2 + 1])
            return bytes([7 * 8]) + v.to_bytes(7, "big")
        if isinstance(v, float):
            return bytes([9 * 8]) + struct.pack(">d", v)
        if isinstance(v, str):
            crudo = v.encode("utf-8")
            return bytes([16 * 8]) + len(crudo).to_bytes(3, "big") + crudo
        if isinstance(v, list):
            salida = bytes([22 * 8]) + len(v).to_bytes(3, "big")
            return salida + b"".join(uno(x) for x in v)
        if isinstance(v, dict):
            salida = bytes([19 * 8]) + len(v).to_bytes(3, "big")
            return salida + b"".join(uno(k) + uno(x) for k, x in v.items())
        raise TypeError(v)

    return bytes([1]) + uno(valor)


def fichero_con(*valores) -> str:
    """Un Journalator.lua de mentira con los bloques que se le pasen."""
    entradas = "\n".join(
        f'["Logs-{i}"] = {{\n["timestamp"] = {1788000000 + i},\n'
        f'["version"] = 1,\n["data"] = "{bloque_de(v)}",\n}},'
        for i, v in enumerate(valores)
    )
    return "JOURNALATOR_CONFIG = {\n}\nJOURNALATOR_ARCHIVE = {\n" + entradas + "\n}\n"


def factura(
    objeto="Zapatillas del culto siseante",
    reino="Sanguino",
    valor=1_000_000,
    comision=50_000,
    deposito=1_500,
    cuando=1788000000,
    personaje="Tbarbar",
    tipo="seller",
):
    return {
        "invoiceType": tipo,
        "itemName": objeto,
        "value": valor,
        "consignment": comision,
        "deposit": deposito,
        "time": cuando,
        "source": {"realm": reino, "character": personaje, "faction": "Alliance"},
    }


def test_el_serializador_de_las_pruebas_va_de_ida_y_vuelta():
    """Si esto falla, no se puede fiar de ninguna prueba que lo use."""
    valor = {"a": [1, 2, {"b": "c"}], "d": None, "e": True, "f": 1.5}
    assert deserializa(_serializa(valor)) == valor


def test_una_venta_sale_con_su_reino_y_su_neto():
    texto = fichero_con({"Invoices": [factura()]})
    (venta,) = ventas_de_texto(texto)

    assert venta.reino == "Sanguino"
    assert venta.objeto == "Zapatillas del culto siseante"
    # Lo que pago el comprador, menos la comision, mas el deposito devuelto.
    assert venta.neto == 1_000_000 - 50_000 + 1_500
    assert venta.cuando == datetime.fromtimestamp(1788000000, timezone.utc)


def test_lo_que_compras_no_cuenta_como_venta():
    texto = fichero_con({"Invoices": [factura(tipo="buyer")]})
    assert ventas_de_texto(texto) == []


def test_la_misma_venta_en_dos_bloques_se_cuenta_una_vez():
    """Las instantaneas del archivo se solapan a proposito."""
    una = factura()
    texto = fichero_con({"Invoices": [una]}, {"Invoices": [una, factura(cuando=1788000900)]})

    assert len(ventas_de_texto(texto)) == 2


def test_un_bloque_roto_no_se_lleva_a_los_demas():
    texto = fichero_con({"Invoices": [factura()]})
    texto = texto.replace('["data"] = "', '["data"] = "zzz', 1)

    # El primero se pierde, pero la lectura no revienta.
    assert ventas_de_texto(texto) == []


def test_una_factura_sin_reino_se_ignora():
    mala = factura()
    mala["source"] = {"character": "Tbarbar"}
    texto = fichero_con({"Invoices": [mala, factura(reino="Kazzak")]})

    assert [v.reino for v in ventas_de_texto(texto)] == ["Kazzak"]


def test_un_fichero_sin_archivo_no_da_nada():
    assert list(bloques("JOURNALATOR_CONFIG = {\n}\n")) == []
    assert ventas_de_texto("JOURNALATOR_CONFIG = {\n}\n") == []


# -- Resumen y ranking -------------------------------------------------------


def venta(reino="Sanguino", objeto="Anillo", neto=1000, dia=5):
    return Venta(reino, objeto, neto, datetime(2026, 9, dia, tzinfo=timezone.utc))


def test_el_resumen_agrupa_por_reino_y_objeto():
    resumen = resumir([venta(neto=100), venta(neto=50), venta(objeto="Capa", neto=7)])

    assert resumen["Sanguino"]["Anillo"] == {
        "ventas": 2,
        "oro": 150,
        "ultima": "2026-09-05",
    }
    assert resumen["Sanguino"]["Capa"]["ventas"] == 1


def test_el_ranking_solo_cuenta_los_objetos_vigilados():
    resumen = resumir(
        [
            venta(reino="Sanguino", objeto="Anillo"),
            venta(reino="Kazzak", objeto="Mena de cobre"),
            venta(reino="Kazzak", objeto="Mena de cobre"),
        ]
    )
    filas, totales = ranking(resumen, {"Anillo"})

    assert [f[0] for f in filas] == ["Sanguino"]
    assert totales == (1, 1000)


def test_sin_filtro_entra_todo():
    resumen = resumir([venta(objeto="Anillo"), venta(objeto="Mena de cobre")])
    _, totales = ranking(resumen)

    assert totales == (2, 2000)


def test_a_igualdad_de_ventas_manda_el_oro():
    """Vender tres cosas de 100.000 importa mas que tres de 500."""
    ventas = []
    for _ in range(3):
        ventas.append(venta(reino="Barato", neto=500))
        ventas.append(venta(reino="Caro", neto=100_000))
    filas, _ = ranking(resumir(ventas))

    assert [f[0] for f in filas] == ["Caro", "Barato"]


def test_un_reino_sin_ventas_vigiladas_no_sale():
    resumen = resumir([venta(reino="Kazzak", objeto="Mena de cobre")])

    assert ranking(resumen, {"Anillo"}) == ([], (0, 0))


# -- El fichero que viaja al repositorio -------------------------------------


def test_escribir_el_resumen_dos_veces_no_cambia_el_fichero(tmp_path):
    """Sin esto el sincronizador haria un commit vacio cada cuarto de hora."""
    ruta = tmp_path / "pc.json"

    assert escribir_resumen(ruta, [venta()]) is True
    assert escribir_resumen(ruta, [venta()]) is False


def test_el_resumen_no_lleva_nombres_de_nadie(tmp_path):
    """Al repositorio no van ni tus personajes ni quien te compro."""
    ruta = tmp_path / "pc.json"
    escribir_resumen(ruta, [venta()])
    escrito = ruta.read_text(encoding="utf-8")

    assert "Tbarbar" not in escrito
    assert "character" not in escrito


def test_las_maquinas_se_suman(tmp_path):
    """Una factura se lee del buzon en una sola maquina, asi que sumar es lo
    correcto: el PC y la Deck nunca ven la misma."""
    escribir_resumen(tmp_path / "pc.json", [venta(neto=100)])
    escribir_resumen(tmp_path / "deck.json", [venta(neto=50)])

    total = leer_resumenes(tmp_path)
    assert total["Sanguino"]["Anillo"] == {
        "ventas": 2,
        "oro": 150,
        "ultima": "2026-09-05",
    }


def test_un_fichero_ilegible_no_se_lleva_a_los_demas(tmp_path):
    (tmp_path / "roto.json").write_text("{esto no es json", encoding="utf-8")
    escribir_resumen(tmp_path / "pc.json", [venta()])

    assert list(leer_resumenes(tmp_path)) == ["Sanguino"]


def test_una_carpeta_que_no_existe_no_rompe(tmp_path):
    assert leer_resumenes(tmp_path / "no_esta") == {}


def test_un_fichero_con_forma_rara_se_ignora(tmp_path):
    (tmp_path / "raro.json").write_text(json.dumps({"reinos": 5}), encoding="utf-8")

    assert leer_resumenes(tmp_path) == {}
