"""Búsqueda de productos en tiempo real (core/busqueda.py)."""
from __future__ import annotations

import pandas as pd

from core.busqueda import buscar_productos, normalizar, producto_por_codigo, stock_por_producto

PRODUCTOS = pd.DataFrame(
    [
        {"id": "OT-000001", "nombre": "Bolso tote rosa", "categoria": "Bolsos", "color": "Rosa", "codigo_barras": None},
        {"id": "OT-000002", "nombre": "Cartera de cuero negra", "categoria": "Carteras", "color": "Negro",
         "codigo_barras": "7701234567890"},
        {"id": "OT-000003", "nombre": "Mini bolso dorado", "categoria": "Bolsos", "color": "Dorado", "codigo_barras": ""},
    ]
)


def test_normalizar_quita_tildes_mayusculas_y_espacios():
    assert normalizar("  Bísutería   ÑANDÚ ") == "bisuteria nandu"


def test_busca_por_partes_del_nombre_en_cualquier_orden_y_sin_tildes():
    assert list(buscar_productos(PRODUCTOS, "rosa TOTE")["id"]) == ["OT-000001"]
    assert list(buscar_productos(PRODUCTOS, "cartéra")["id"]) == ["OT-000002"]
    assert buscar_productos(PRODUCTOS, "zzz").empty
    assert buscar_productos(PRODUCTOS, "   ").empty


def test_ordena_primero_los_que_empiezan_por_lo_escrito():
    assert list(buscar_productos(PRODUCTOS, "bolso")["id"]) == ["OT-000001", "OT-000003"]
    assert list(buscar_productos(PRODUCTOS, "mini")["id"]) == ["OT-000003"]


def test_busca_por_codigos_parciales_y_categoria():
    assert list(buscar_productos(PRODUCTOS, "770123")["id"]) == ["OT-000002"]
    assert list(buscar_productos(PRODUCTOS, "20000003")["id"]) == ["OT-000003"]
    assert len(buscar_productos(PRODUCTOS, "bolsos", limite=1)) == 1


def test_coincidencia_exacta_por_codigo_para_el_lector():
    assert producto_por_codigo(PRODUCTOS, "7701234567890")["id"] == "OT-000002"
    assert producto_por_codigo(PRODUCTOS, "20000003")["id"] == "OT-000003"
    assert producto_por_codigo(PRODUCTOS, "ot'000001\r")["id"] == "OT-000001"
    assert producto_por_codigo(PRODUCTOS, "bolso") is None  # un nombre nunca se agrega solo
    assert producto_por_codigo(PRODUCTOS, "") is None
    assert producto_por_codigo(PRODUCTOS.iloc[0:0], "20000001") is None


def test_stock_por_producto_suma_sedes():
    stock = pd.DataFrame([
        {"producto_id": "OT-000001", "cantidad": 3}, {"producto_id": "OT-000001", "cantidad": "2"},
        {"producto_id": "OT-000002", "cantidad": None},
    ])
    assert stock_por_producto(stock) == {"OT-000001": 5, "OT-000002": 0}
    assert stock_por_producto(stock.iloc[0:0]) == {}
