"""Traduccion de nombre de reino a connected realm id."""

import pytest

from wowalerts.blizzard import BlizzardError
from wowalerts.realms import RealmResolutionError, resolve_connected_realms
from wowalerts.state import RealmIdCache


class ClienteFalso:
    def __init__(self, por_slug=None, indice=None, fallos=()):
        self.por_slug = por_slug or {}
        self.indice = indice or []
        self.fallos = set(fallos)
        self.slugs_pedidos = []

    def connected_realm_id_for(self, slug):
        self.slugs_pedidos.append(slug)
        if slug in self.fallos:
            raise BlizzardError("boom")
        return self.por_slug.get(slug)

    def realm_index(self):
        return self.indice


def cache(tmp_path):
    return RealmIdCache(tmp_path / "realm_ids.json")


def test_resuelve_por_slug(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    assert resolve_connected_realms(cliente, cache(tmp_path), ["sanguino"]) == {
        "sanguino": 1379
    }


def test_usa_la_cache_y_no_repite_la_peticion(tmp_path):
    guardada = cache(tmp_path)
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    resolve_connected_realms(cliente, guardada, ["sanguino"])
    guardada.save()

    otro = ClienteFalso()
    assert resolve_connected_realms(otro, cache(tmp_path), ["sanguino"]) == {
        "sanguino": 1379
    }
    assert otro.slugs_pedidos == []


def test_cae_al_indice_cuando_el_slug_no_vale(tmp_path):
    # 'dunmodr' no le suena a Blizzard; por el indice se llega a 'dun-modr'.
    cliente = ClienteFalso(
        por_slug={"dun-modr": 1379},
        indice=[{"slug": "dun-modr", "name": "Dun Modr"}],
    )
    assert resolve_connected_realms(cliente, cache(tmp_path), ["dunmodr"]) == {
        "dunmodr": 1379
    }
    assert cliente.slugs_pedidos == ["dunmodr", "dun-modr"]


def test_reino_desconocido_da_error_con_su_nombre(tmp_path):
    cliente = ClienteFalso(por_slug={}, indice=[])
    with pytest.raises(RealmResolutionError, match="inventado"):
        resolve_connected_realms(cliente, cache(tmp_path), ["inventado"])


def test_un_reino_que_falla_no_tumba_a_los_demas(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379}, fallos=["roto"], indice=[])
    resultado = resolve_connected_realms(
        cliente, cache(tmp_path), ["sanguino", "roto"], strict=False
    )
    assert resultado == {"sanguino": 1379}


def test_no_repite_la_consulta_de_un_reino_duplicado(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    resolve_connected_realms(cliente, cache(tmp_path), ["sanguino", "sanguino"])
    assert cliente.slugs_pedidos == ["sanguino"]
