"""Pruebas de core/costing.py (R5: costo promedio ponderado + entrada)."""
from __future__ import annotations

import pytest

from core import inventory, schema
from core.costing import costo_promedio_ponderado, registrar_entrada
from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError


def test_costo_promedio_con_stock_previo_cero_usa_costo_entrada():
    # Caso de borde R5: stock_prev <= 0 -> se usa costo_entrada directo.
    assert costo_promedio_ponderado(0, 0, 10, 5000) == 5000


def test_costo_promedio_con_stock_previo_negativo_usa_costo_entrada():
    assert costo_promedio_ponderado(-3, 1000, 10, 5000) == 5000


def test_costo_promedio_ponderado_normal():
    # (10*1000 + 5*2000) / 15 = 20000/15 = 1333.33... -> redondeo normal.
    assert costo_promedio_ponderado(10, 1000, 5, 2000) == 1333


def test_costo_promedio_redondeo_mitad_arriba():
    # (1*1000 + 1*1001) / 2 = 1000.5 -> redondea a 1001 (mitad hacia arriba).
    assert costo_promedio_ponderado(1, 1000, 1, 1001) == 1001


def test_costo_promedio_rechaza_cantidad_no_positiva():
    with pytest.raises(ValueError):
        costo_promedio_ponderado(10, 1000, 0, 500)


def test_costo_promedio_rechaza_costo_entrada_negativo():
    with pytest.raises(ValueError):
        costo_promedio_ponderado(10, 1000, 5, -1)


def _crear_producto_base(storage, costo=1000, precio=2000, stock_inicial=0):
    resultado = inventory.crear_producto(
        storage,
        ADMIN,
        nombre="Bolso de prueba",
        usuario_id="U-1",
        costo=costo,
        precio=precio,
        stock_inicial=stock_inicial,
    )
    return resultado["id"]


def test_registrar_entrada_actualiza_costo_stock_y_kardex(storage):
    producto_id = _crear_producto_base(storage, costo=1000, precio=2000, stock_inicial=10)

    resultado = registrar_entrada(
        storage,
        ADMIN,
        producto_id=producto_id,
        cantidad=5,
        costo_unitario=2000,
        usuario_id="U-1",
    )

    # (10*1000 + 5*2000) / 15 = 1333 (truncado hacia abajo, no hay mitad exacta)
    assert resultado["costo_nuevo"] == 1333
    assert resultado["stock_nuevo"] == 15

    productos = storage.read_sheet(schema.PRODUCTOS)
    fila = productos[productos["id"] == producto_id].iloc[0]
    assert int(fila["costo"]) == 1333

    stock_df = storage.read_sheet(schema.STOCK)
    fila_stock = stock_df[stock_df["producto_id"] == producto_id].iloc[0]
    assert int(fila_stock["cantidad"]) == 15

    movimientos = storage.read_sheet(schema.MOVIMIENTOS)
    entradas = movimientos[(movimientos["producto_id"] == producto_id) & (movimientos["tipo"] == "entrada")]
    assert len(entradas) == 1
    fila_mov = entradas.iloc[0]
    assert int(fila_mov["cantidad"]) == 5
    assert int(fila_mov["stock_antes"]) == 10
    assert int(fila_mov["stock_despues"]) == 15


def test_registrar_entrada_sin_stock_previo_usa_costo_entrada(storage):
    producto_id = _crear_producto_base(storage, costo=0, precio=2000, stock_inicial=0)

    resultado = registrar_entrada(
        storage,
        ADMIN,
        producto_id=producto_id,
        cantidad=10,
        costo_unitario=3000,
        usuario_id="U-1",
    )
    assert resultado["costo_nuevo"] == 3000
    assert resultado["stock_nuevo"] == 10


def test_registrar_entrada_rechaza_producto_inexistente(storage):
    with pytest.raises(ValueError):
        registrar_entrada(
            storage,
            ADMIN,
            producto_id="OT-999999",
            cantidad=5,
            costo_unitario=1000,
            usuario_id="U-1",
        )


def test_registrar_entrada_rechaza_cantidad_no_positiva(storage):
    producto_id = _crear_producto_base(storage)
    with pytest.raises(ValueError):
        registrar_entrada(
            storage,
            ADMIN,
            producto_id=producto_id,
            cantidad=0,
            costo_unitario=1000,
            usuario_id="U-1",
        )


def test_vendedor_no_puede_registrar_entrada(storage):
    producto_id = _crear_producto_base(storage)
    with pytest.raises(PermisoDenegadoError):
        registrar_entrada(
            storage,
            VENDEDOR,
            producto_id=producto_id,
            cantidad=5,
            costo_unitario=1000,
            usuario_id="U-2",
        )
    # Nada debió escribirse: el stock sigue igual que antes del intento.
    stock_df = storage.read_sheet(schema.STOCK)
    assert stock_df.empty or (stock_df["producto_id"] == producto_id).sum() == 0


def test_registrar_entrada_transaccion_atomica_si_falla_dentro(storage):
    # El producto no existe: el ValueError se lanza DENTRO de storage.transaction()
    # (después de abrirla), y aun así no debe quedar nada a medias (R6).
    movimientos_antes = len(storage.read_sheet(schema.MOVIMIENTOS))
    stock_antes = len(storage.read_sheet(schema.STOCK))
    with pytest.raises(ValueError):
        registrar_entrada(
            storage,
            ADMIN,
            producto_id="OT-999999",
            cantidad=5,
            costo_unitario=1000,
            usuario_id="U-1",
        )
    assert len(storage.read_sheet(schema.MOVIMIENTOS)) == movimientos_antes
    assert len(storage.read_sheet(schema.STOCK)) == stock_antes
    assert storage.transacciones_confirmadas == 0
