"""Prueba de `scripts/seed_db.sembrar_config` con `FakeStorage` (sin red,
§B2: "Prueba incluida en tests (con FakeStorage)")."""
from __future__ import annotations

from core import schema
from scripts.seed_db import VALORES_CONFIG, sembrar_config


def test_sembrar_config_escribe_todas_las_claves_esperadas(storage):
    with storage.transaction() as tx:
        sembrar_config(tx)

    df = storage.read_sheet(schema.CONFIG)
    config = dict(zip(df["clave"], df["valor"]))
    for clave, esperado in VALORES_CONFIG.items():
        assert config.get(clave) == esperado


def test_sembrar_config_no_toca_hojas_transaccionales_ni_catalogo(storage):
    with storage.transaction() as tx:
        sembrar_config(tx)

    for nombre in schema.SHEET_NAMES:
        if nombre == schema.CONFIG:
            continue
        assert storage.read_sheet(nombre).empty, f"'{nombre}' debería seguir vacía tras la siembra inicial"


def test_metodos_pago_sembrados_son_todos_validos():
    metodos = VALORES_CONFIG["negocio_metodos_pago_activos"].split("|")
    assert set(metodos) == schema.METODOS_PAGO


def test_categorias_sembradas_no_tienen_duplicados_ni_vacias():
    categorias = VALORES_CONFIG["negocio_categorias"].split("|")
    assert len(categorias) == len(set(categorias))
    assert all(c.strip() for c in categorias)


def test_permitir_vender_sin_stock_queda_desactivado_por_defecto():
    assert VALORES_CONFIG["permitir_vender_sin_stock"] == "false"
