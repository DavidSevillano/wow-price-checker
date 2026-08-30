import pytest

from wowalerts.config import ConfigError, load_config

VALID = """
region: eu
items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
  - name: "Venom Rite Mantle"
    item_id: 12345
    max_price_by_ilvl: { 311: 120000 }
bonus_ilvl_map:
  12843: 311
settings:
  max_workers: 4
"""


def write(tmp_path, text, name="config.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_carga_una_configuracion_valida(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.region == "eu"
    assert config.locale == "en_GB"
    assert len(config.items) == 2
    assert config.items[0].max_price_by_ilvl == {298: 9000, 311: 90000}
    assert config.items[1].item_id == 12345
    assert config.bonus_ilvl_map == {12843: 311}
    assert config.settings.max_workers == 4
    # Las opciones no indicadas conservan su valor por defecto.
    assert config.settings.state_retention_runs == 72


def test_umbral_mas_barato_de_un_objeto(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.items[0].cheapest_threshold_gold == 9000


def test_threshold_gold_devuelve_none_para_un_ilvl_no_listado(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.items[0].threshold_gold(311) == 90000
    assert config.items[0].threshold_gold(305) is None


def test_fichero_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="No encuentro el fichero"):
        load_config(tmp_path / "no-existe.yaml")


def test_yaml_invalido(tmp_path):
    with pytest.raises(ConfigError, match="no es YAML valido"):
        load_config(write(tmp_path, "items: [oops\n  - :"))


def test_region_desconocida(tmp_path):
    with pytest.raises(ConfigError, match="'region'"):
        load_config(write(tmp_path, "region: marte\nitems:\n  - name: x\n    max_price_by_ilvl: {1: 1}\n"))


def test_lista_de_objetos_vacia(tmp_path):
    with pytest.raises(ConfigError, match="'items'"):
        load_config(write(tmp_path, "region: eu\nitems: []\n"))


def test_objeto_repetido(tmp_path):
    text = """
region: eu
items:
  - name: "Repetido"
    max_price_by_ilvl: { 311: 1 }
  - name: "Repetido"
    max_price_by_ilvl: { 311: 2 }
"""
    with pytest.raises(ConfigError, match="repetido"):
        load_config(write(tmp_path, text))


def test_objeto_sin_tabla_de_precios(tmp_path):
    text = 'region: eu\nitems:\n  - name: "Sin precios"\n'
    with pytest.raises(ConfigError, match="max_price_by_ilvl"):
        load_config(write(tmp_path, text))


def test_precio_negativo(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: -5 }\n'
    with pytest.raises(ConfigError, match="mayor que 0"):
        load_config(write(tmp_path, text))


def test_precio_no_numerico(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: "barato" }\n'
    with pytest.raises(ConfigError, match="numeros enteros"):
        load_config(write(tmp_path, text))


def test_ilvl_escrito_como_texto_se_convierte(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { "311": "90000" }\n'
    config = load_config(write(tmp_path, text))
    assert config.items[0].max_price_by_ilvl == {311: 90000}


def test_opcion_de_settings_desconocida(tmp_path):
    text = VALID + "\n  tipo_mal_escrito: 3\n"
    with pytest.raises(ConfigError, match="no reconozco"):
        load_config(write(tmp_path, text))


def test_max_workers_invalido(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\nsettings:\n  max_workers: 0\n'
    with pytest.raises(ConfigError, match="max_workers"):
        load_config(write(tmp_path, text))


def test_umbral_de_fallos_fuera_de_rango(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\nsettings:\n  failure_ratio_threshold: 1.5\n'
    with pytest.raises(ConfigError, match="failure_ratio_threshold"):
        load_config(write(tmp_path, text))


def test_el_config_del_repositorio_es_valido():
    """El config.yaml que se entrega tiene que cargar sin tocarlo."""
    config = load_config("config.yaml")
    assert config.items
    assert config.bonus_ilvl_map
