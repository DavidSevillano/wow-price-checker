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


def test_valores_por_defecto_del_reintento_por_volcado_viejo(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings

    assert settings.dump_minute == 31
    assert settings.stale_retries == 2
    assert settings.stale_retry_wait_seconds == 120


def test_se_puede_desactivar_el_reintento(tmp_path):
    text = VALID + "  stale_retries: 0\n"

    assert load_config(write(tmp_path, text)).settings.stale_retries == 0


def test_dump_minute_fuera_de_rango(tmp_path):
    with pytest.raises(ConfigError, match="entre 0 y 59"):
        load_config(write(tmp_path, VALID + "  dump_minute: 60\n"))


def test_stale_retries_negativo(tmp_path):
    with pytest.raises(ConfigError, match="no puede ser negativo"):
        load_config(write(tmp_path, VALID + "  stale_retries: -1\n"))


def test_espera_entre_reintentos_demasiado_corta(tmp_path):
    with pytest.raises(ConfigError, match="al menos 1 segundo"):
        load_config(write(tmp_path, VALID + "  stale_retry_wait_seconds: 0\n"))


# -- Ajustes de las ventas --------------------------------------------------


def test_ajustes_de_venta_por_defecto(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings
    assert settings.ah_cut_pct == 5
    assert settings.listing_hours == 12


def test_ah_cut_pct_se_puede_cambiar(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  ah_cut_pct: 0\n"
    )
    assert load_config(write(tmp_path, text)).settings.ah_cut_pct == 0


def test_ah_cut_pct_fuera_de_rango(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  ah_cut_pct: 100\n"
    )
    with pytest.raises(ConfigError, match="ah_cut_pct"):
        load_config(write(tmp_path, text))


def test_listing_hours_fuera_de_rango(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  listing_hours: 0\n"
    )
    with pytest.raises(ConfigError, match="listing_hours"):
        load_config(write(tmp_path, text))


# -- Ventana de silencio ----------------------------------------------------


def test_sin_ventana_de_silencio_por_defecto(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings
    assert settings.silencio_desde == 0
    assert settings.silencio_hasta == 0
    assert settings.zona_horaria == "Europe/Madrid"


def test_la_ventana_de_silencio_se_lee(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  silencio_desde: 1\n  silencio_hasta: 9\n"
    )
    settings = load_config(write(tmp_path, text)).settings
    assert (settings.silencio_desde, settings.silencio_hasta) == (1, 9)


def test_una_hora_que_no_es_del_reloj_da_error(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  silencio_desde: 24\n"
    )
    with pytest.raises(ConfigError, match="silencio_desde"):
        load_config(write(tmp_path, text))


def test_una_zona_horaria_inventada_se_detecta_al_arrancar(tmp_path):
    """Mejor fallar al cargar el config que a las 3 de la manana."""
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        'settings:\n  zona_horaria: "Europa/Madriz"\n'
    )
    with pytest.raises(ConfigError, match="zona_horaria"):
        load_config(write(tmp_path, text))
