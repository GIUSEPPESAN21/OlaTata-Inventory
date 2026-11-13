"""Autorreparación de la configuración del negocio (core/config_inicial.py).

Escenario real de producción: un reinicio del servidor publicó un libro
vacío y se perdieron 12 claves de CONFIG. La app ahora las restaura solas,
sin pisar nunca lo que el dueño ya editó.
"""
from __future__ import annotations

from core.config_inicial import VALORES_CONFIG_INICIALES, claves_faltantes, completar_config_faltante
from scripts.seed_db import VALORES_CONFIG


def test_base_sin_config_recupera_todas_las_claves(storage):
    assert set(claves_faltantes(storage)) == set(VALORES_CONFIG_INICIALES)
    with storage.transaction() as tx:
        agregadas = completar_config_faltante(tx)
    assert set(agregadas) == set(VALORES_CONFIG_INICIALES)
    assert claves_faltantes(storage) == []
    assert storage.get_config("negocio_categorias").startswith("Bolsos|")


def test_nunca_pisa_un_valor_ya_editado(storage):
    with storage.transaction() as tx:
        tx.set_config("negocio_nombre", "Mi tienda editada")
        tx.set_config("sesion_minutos", "60")
    with storage.transaction() as tx:
        agregadas = completar_config_faltante(tx)
    assert "negocio_nombre" not in agregadas and "sesion_minutos" not in agregadas
    assert storage.get_config("negocio_nombre") == "Mi tienda editada"
    assert storage.get_config("sesion_minutos") == "60"


def test_es_idempotente(storage):
    with storage.transaction() as tx:
        completar_config_faltante(tx)
    with storage.transaction() as tx:
        assert completar_config_faltante(tx) == []


def test_seed_db_usa_la_misma_fuente_de_verdad():
    assert VALORES_CONFIG is VALORES_CONFIG_INICIALES
