"""Pruebas de `core.returns` (R9: anulación y devolución/cambio)."""
from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd
import pytest

from core import schema
from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError
from core.returns import (
    DevolucionInvalidaError,
    VentaNoEncontradaError,
    anular_venta,
    registrar_devolucion_cambio,
)
from core.sales import confirmar_venta
from core.timeutil import UTC


def _seed_producto(storage, producto_id="P-1", precio=90_000, costo=50_000, stock=10):
    with storage.transaction() as tx:
        productos_df = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": producto_id,
                    "nombre": "Bolso Negro",
                    "categoria": "Bolsos",
                    "color": "Negro",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": costo,
                    "precio": precio,
                    "stock_minimo": 1,
                    "codigo_barras": producto_id,
                    "activo": True,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([productos_df, nueva], ignore_index=True))
        stock_df = tx.read_sheet(schema.STOCK)
        nueva_stock = pd.DataFrame(
            [
                {
                    "producto_id": producto_id,
                    "sede_id": schema.SEDE_PRINCIPAL,
                    "cantidad": stock,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
        tx.write_sheet(schema.STOCK, pd.concat([stock_df, nueva_stock], ignore_index=True))


def _vender(storage, cantidad=2, precio=90_000):
    return confirmar_venta(
        storage,
        VENDEDOR,
        str(uuid.uuid4()),
        [{"producto_id": "P-1", "cantidad": cantidad}],
        [{"metodo": "efectivo", "monto": precio * cantidad}],
        None,
        None,
        "tienda",
        None,
        "U-1",
        "Ana",
    )


# --------------------------------------------------------------- anulación


def test_vendedor_no_puede_anular_llamando_directo_a_core(storage):
    _seed_producto(storage)
    venta = _vender(storage)
    with pytest.raises(PermisoDenegadoError):
        anular_venta(storage, VENDEDOR, venta.numero, "Cliente se arrepintió")


def test_admin_puede_anular_motivo_obligatorio(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=2)
    with pytest.raises(DevolucionInvalidaError):
        anular_venta(storage, ADMIN, venta.numero, "")  # motivo vacío


def test_anular_venta_repone_stock_y_no_borra_la_fila(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=2)
    stock_antes_anular = int(storage.read_sheet(schema.STOCK).iloc[0]["cantidad"])
    assert stock_antes_anular == 8

    anular_venta(storage, ADMIN, venta.numero, "Cliente se arrepintió", usuario_id="U-ADMIN")

    ventas_df = storage.read_sheet(schema.VENTAS)
    assert len(ventas_df) == 1  # NO se borra
    fila = ventas_df.iloc[0]
    assert fila["estado"] == "anulada"
    assert fila["anulada_motivo"] == "Cliente se arrepintió"
    assert fila["anulada_por"] == "U-ADMIN"

    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 10  # se repuso

    movimientos_df = storage.read_sheet(schema.MOVIMIENTOS)
    anulaciones = movimientos_df[movimientos_df["tipo"] == "anulacion"]
    assert len(anulaciones) == 1
    assert anulaciones.iloc[0]["cantidad"] == 2


def test_anular_venta_inexistente_lanza(storage):
    _seed_producto(storage)
    with pytest.raises(VentaNoEncontradaError):
        anular_venta(storage, ADMIN, "2099-01-9999", "motivo")


def test_anular_venta_ya_anulada_es_idempotente(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=2)
    anular_venta(storage, ADMIN, venta.numero, "motivo 1")
    stock_tras_primera = int(storage.read_sheet(schema.STOCK).iloc[0]["cantidad"])
    anular_venta(storage, ADMIN, venta.numero, "motivo 2")  # no debe reponer dos veces
    stock_tras_segunda = int(storage.read_sheet(schema.STOCK).iloc[0]["cantidad"])
    assert stock_tras_primera == stock_tras_segunda == 10


# ---------------------------------------------------------- devolución/cambio


def test_devolucion_parcial_repone_stock_y_resta_en_el_dia_en_que_se_hace(storage, monkeypatch):
    import core.sales as sales_mod

    _seed_producto(storage, stock=10)
    monkeypatch.setattr(sales_mod, "now_utc", lambda: datetime(2026, 11, 1, 15, 0, tzinfo=UTC))
    venta = _vender(storage, cantidad=3)
    assert venta.fecha_local == "2026-11-01"

    monkeypatch.undo()  # la devolución ocurre "hoy" (tiempo real), no el día de la venta
    dev = registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta.numero,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
        tipo="devolucion",
        motivo="No le gustó el color",
        reembolso_metodo="efectivo",
        usuario_id="U-1",
    )
    assert dev.fecha_local != "2026-11-01"  # NO es la fecha de la venta original
    assert dev.reembolso_monto == 90_000

    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 8  # 10 - 3 (venta) + 1 (devolución)

    movimientos_df = storage.read_sheet(schema.MOVIMIENTOS)
    devoluciones_mov = movimientos_df[movimientos_df["tipo"] == "devolucion"]
    assert len(devoluciones_mov) == 1
    assert devoluciones_mov.iloc[0]["fecha_hora_utc"] != venta.fecha_hora_utc


def test_devolucion_merma_no_repone_stock(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=2)
    stock_tras_venta = int(storage.read_sheet(schema.STOCK).iloc[0]["cantidad"])

    registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta.numero,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "merma"}],
        tipo="devolucion",
        motivo="Llegó dañado",
        reembolso_metodo="efectivo",
    )
    stock_tras_devolucion = int(storage.read_sheet(schema.STOCK).iloc[0]["cantidad"])
    assert stock_tras_devolucion == stock_tras_venta  # no entra a stock

    movimientos_df = storage.read_sheet(schema.MOVIMIENTOS)
    assert (movimientos_df["tipo"] == "devolucion").sum() == 0  # sin variación de stock, sin movimiento


def test_devolucion_no_puede_superar_lo_vendido_menos_ya_devuelto(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=2)
    registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta.numero,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 2, "destino": "stock"}],
        tipo="devolucion",
        motivo="No le gustó",
        reembolso_metodo="efectivo",
    )
    with pytest.raises(DevolucionInvalidaError):
        registrar_devolucion_cambio(
            storage,
            VENDEDOR,
            venta.numero,
            items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
            tipo="devolucion",
            motivo="Intento de devolver de más",
            reembolso_metodo="efectivo",
        )


def test_devolucion_motivo_obligatorio(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=1)
    with pytest.raises(DevolucionInvalidaError):
        registrar_devolucion_cambio(
            storage,
            VENDEDOR,
            venta.numero,
            items_devueltos=[{"producto_id": "P-1", "cantidad": 1}],
            tipo="devolucion",
            motivo="",
            reembolso_metodo="efectivo",
        )


def test_reembolso_metodo_cambio_queda_registrado_como_saldo_a_favor(storage):
    _seed_producto(storage, stock=10)
    venta = _vender(storage, cantidad=1)
    dev = registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta.numero,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
        tipo="cambio",
        motivo="Quiere otro producto",
        reembolso_metodo="cambio",
    )
    assert dev.reembolso_metodo == "cambio"
    assert dev.tipo == "cambio"
    devoluciones_df = storage.read_sheet(schema.DEVOLUCIONES)
    assert devoluciones_df.iloc[0]["reembolso_metodo"] == "cambio"


def test_venta_de_mes_archivado_se_puede_resolver_desde_fuera(storage):
    """La devolución recibe la venta YA RESUELTA (dict), sin tocar la
    hoja VENTAS viva -- simula una venta de un mes ya archivado."""
    venta_resuelta = {
        "numero": "2026-01-0001",
        "items": [
            {
                "producto_id": "P-1",
                "nombre_snapshot": "Bolso Negro",
                "cantidad": 2,
                "precio_unitario": 90_000,
                "costo_unitario": 50_000,
                "total_linea": 180_000,
            }
        ],
    }
    _seed_producto(storage, stock=5)
    dev = registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta_resuelta,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
        tipo="devolucion",
        motivo="Venta de un mes archivado",
        reembolso_metodo="efectivo",
    )
    assert dev.venta_numero == "2026-01-0001"
    assert dev.reembolso_monto == 90_000
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 6  # 5 + 1 repuesto
