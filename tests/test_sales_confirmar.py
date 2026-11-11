"""Pruebas de `core.sales.confirmar_venta` (R1, R3, R5-R8, R10, R11)."""
from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd
import pytest

from core import schema
from core.permissions import VENDEDOR, PermisoDenegadoError
from core.sales import (
    PagoInvalidoError,
    StockInsuficienteError,
    VentaInvalidaError,
    confirmar_venta,
)
from core.timeutil import UTC, local_date


def _seed_producto(
    storage, producto_id="P-1", nombre="Bolso Negro", precio=90_000, costo=50_000, stock=10, activo=True
):
    with storage.transaction() as tx:
        productos_df = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": producto_id,
                    "nombre": nombre,
                    "categoria": "Bolsos",
                    "color": "Negro",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": costo,
                    "precio": precio,
                    "stock_minimo": 1,
                    "codigo_barras": producto_id,
                    "activo": activo,
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
    return producto_id


def _items(producto_id="P-1", cantidad=1):
    return [{"producto_id": producto_id, "cantidad": cantidad}]


def _pagos(monto):
    return [{"metodo": "efectivo", "monto": monto}]


# --------------------------------------------------------------- permisos


def test_vendedor_puede_vender(storage):
    _seed_producto(storage)
    venta = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000),
        None, None, "tienda", None, "U-1", "Ana",
    )
    assert venta.total == 90_000


def test_rol_invalido_no_puede_vender(storage):
    _seed_producto(storage)
    with pytest.raises(PermisoDenegadoError):
        confirmar_venta(
            storage, "fantasma", str(uuid.uuid4()), _items(), _pagos(90_000),
            None, None, "tienda", None, "U-1", "Ana",
        )


# --------------------------------------------------------- venta atómica


def test_venta_atomica_completa_escribe_todas_las_hojas(storage):
    _seed_producto(storage, stock=10)
    venta = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(cantidad=2), _pagos(180_000),
        None, None, "tienda", {"nombre": "Clienta X"}, "U-1", "Ana",
    )
    assert venta.numero.endswith("-0001")
    assert venta.subtotal == 180_000
    assert venta.total == 180_000
    assert venta.estado == "completada"

    ventas_df = storage.read_sheet(schema.VENTAS)
    assert len(ventas_df) == 1

    items_df = storage.read_sheet(schema.VENTA_ITEMS)
    assert len(items_df) == 1
    assert items_df.iloc[0]["precio_unitario"] == 90_000
    assert items_df.iloc[0]["costo_unitario"] == 50_000  # snapshot (R5)

    pagos_df = storage.read_sheet(schema.PAGOS)
    assert len(pagos_df) == 1
    assert pagos_df.iloc[0]["monto"] == 180_000

    movimientos_df = storage.read_sheet(schema.MOVIMIENTOS)
    assert len(movimientos_df) == 1
    mov = movimientos_df.iloc[0]
    assert mov["tipo"] == "venta"
    assert mov["cantidad"] == -2
    assert mov["stock_antes"] == 10
    assert mov["stock_despues"] == 8

    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 8

    # R4: stock = Σ movimientos (contando también el stock inicial sembrado)
    assert int(stock_df.iloc[0]["cantidad"]) == 10 + int(movimientos_df["cantidad"].sum())


def test_snapshot_de_precio_no_se_altera_si_el_precio_cambia_despues(storage):
    _seed_producto(storage, precio=90_000)
    confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000),
        None, None, "tienda", None, "U-1", "Ana",
    )
    # Cambiamos el precio del producto DESPUÉS de la venta.
    with storage.transaction() as tx:
        productos_df = tx.read_sheet(schema.PRODUCTOS)
        productos_df.loc[productos_df["id"] == "P-1", "precio"] = 150_000
        tx.write_sheet(schema.PRODUCTOS, productos_df)

    items_df = storage.read_sheet(schema.VENTA_ITEMS)
    assert items_df.iloc[0]["precio_unitario"] == 90_000  # el historial no cambia


# ---------------------------------------------------------------- stock


def test_stock_insuficiente_se_rechaza_y_no_deja_nada(storage):
    _seed_producto(storage, stock=1)
    with pytest.raises(StockInsuficienteError):
        confirmar_venta(
            storage, VENDEDOR, str(uuid.uuid4()), _items(cantidad=5), _pagos(450_000),
            None, None, "tienda", None, "U-1", "Ana",
        )
    assert storage.read_sheet(schema.VENTAS).empty
    assert storage.read_sheet(schema.MOVIMIENTOS).empty
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 1  # sin cambios


def test_permitir_vender_sin_stock_permite_pero_queda_en_alerta(storage):
    _seed_producto(storage, stock=1)
    with storage.transaction() as tx:
        tx.set_config("permitir_vender_sin_stock", "true")

    venta = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(cantidad=3), _pagos(270_000),
        None, None, "tienda", None, "U-1", "Ana",
    )
    assert venta.total == 270_000
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == -2  # negativo = "en alerta"


# --------------------------------------------------------------- pagos (R6)


def test_suma_de_pagos_distinta_del_total_se_rechaza(storage):
    _seed_producto(storage)
    with pytest.raises(PagoInvalidoError):
        confirmar_venta(
            storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(50_000),
            None, None, "tienda", None, "U-1", "Ana",
        )
    assert storage.read_sheet(schema.VENTAS).empty


def test_pago_dividido_en_dos_metodos(storage):
    _seed_producto(storage)
    venta = confirmar_venta(
        storage,
        VENDEDOR,
        str(uuid.uuid4()),
        _items(),
        [{"metodo": "efectivo", "monto": 40_000}, {"metodo": "datafono", "monto": 50_000}],
        None,
        None,
        "tienda",
        None,
        "U-1",
        "Ana",
    )
    assert venta.total == 90_000
    pagos_df = storage.read_sheet(schema.PAGOS)
    assert len(pagos_df) == 2
    assert pagos_df["monto"].sum() == 90_000


def test_metodo_de_pago_invalido_se_rechaza(storage):
    _seed_producto(storage)
    with pytest.raises(PagoInvalidoError):
        confirmar_venta(
            storage, VENDEDOR, str(uuid.uuid4()), _items(),
            [{"metodo": "bitcoin", "monto": 90_000}],
            None, None, "tienda", None, "U-1", "Ana",
        )


# --------------------------------------------------------------- idempotencia (R6)


def test_doble_clic_con_misma_idempotency_key_no_duplica(storage):
    _seed_producto(storage, stock=10)
    clave = str(uuid.uuid4())
    venta1 = confirmar_venta(
        storage, VENDEDOR, clave, _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    venta2 = confirmar_venta(
        storage, VENDEDOR, clave, _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    assert venta1.id == venta2.id
    assert venta1.numero == venta2.numero
    assert len(storage.read_sheet(schema.VENTAS)) == 1
    assert len(storage.read_sheet(schema.VENTA_ITEMS)) == 1
    assert len(storage.read_sheet(schema.MOVIMIENTOS)) == 1
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 9  # solo se descontó UNA vez


def test_idempotency_key_vacia_se_rechaza(storage):
    _seed_producto(storage)
    with pytest.raises(VentaInvalidaError):
        confirmar_venta(storage, VENDEDOR, "", _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana")


# --------------------------------------------------------------- descuentos (R7)


def test_descuento_global_porcentual_nunca_supera_el_subtotal(storage):
    _seed_producto(storage, precio=100_000, stock=5)
    venta = confirmar_venta(
        storage,
        VENDEDOR,
        str(uuid.uuid4()),
        _items(),
        _pagos(0),
        {"tipo": "porcentaje", "valor": 200},  # 200%: se debe limitar al 100% del subtotal
        None,
        "tienda",
        None,
        "U-1",
        "Ana",
    )
    assert venta.descuento_total == 100_000
    assert venta.total == 0


def test_descuento_de_linea_y_global_se_registran_y_envio_aparte(storage):
    _seed_producto(storage, precio=100_000, stock=5)
    venta = confirmar_venta(
        storage,
        VENDEDOR,
        str(uuid.uuid4()),
        [{"producto_id": "P-1", "cantidad": 1, "descuento_linea": 10_000}],
        _pagos(95_000),
        {"tipo": "monto", "valor": 5_000},
        {"cobrado": 10_000, "ciudad": "Tuluá"},
        "tienda",
        None,
        "U-1",
        "Ana",
    )
    # subtotal (bruto) = 100_000; descuento_total = 10_000 (línea) + 5_000 (global) = 15_000
    assert venta.subtotal == 100_000
    assert venta.descuento_total == 15_000
    # total = 100_000 - 15_000 + 10_000(envío) = 95_000
    assert venta.total == 95_000
    # el envío no cuenta como venta de producto: no infla "subtotal"
    assert venta.envio_cobrado == 10_000
    assert venta.subtotal == 100_000


def test_canal_invalido_se_rechaza(storage):
    _seed_producto(storage)
    with pytest.raises(VentaInvalidaError):
        confirmar_venta(
            storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000),
            None, None, "canal-fantasma", None, "U-1", "Ana",
        )


# --------------------------------------------------------------- numeración (R10)


def test_numeracion_reinicia_por_mes(storage, monkeypatch):
    import core.sales as sales_mod

    _seed_producto(storage, stock=100)

    monkeypatch.setattr(sales_mod, "now_utc", lambda: datetime(2026, 11, 15, 12, 0, tzinfo=UTC))
    v1 = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    v2 = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    assert v1.numero == "2026-11-0001"
    assert v2.numero == "2026-11-0002"

    monkeypatch.setattr(sales_mod, "now_utc", lambda: datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    v3 = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    assert v3.numero == "2026-12-0001"  # reinicia por mes (R10)


# --------------------------------------------------------------- R2: corte Bogotá


def test_venta_23_30_bogota_cuenta_en_el_dia_correcto(storage, monkeypatch):
    import core.sales as sales_mod

    _seed_producto(storage, stock=10)
    # 23:30 de Bogotá del 10-nov == 04:30 UTC del 11-nov (Bogotá es UTC-5, sin horario de verano).
    momento_utc = datetime(2026, 11, 11, 4, 30, tzinfo=UTC)
    monkeypatch.setattr(sales_mod, "now_utc", lambda: momento_utc)

    venta = confirmar_venta(
        storage, VENDEDOR, str(uuid.uuid4()), _items(), _pagos(90_000), None, None, "tienda", None, "U-1", "Ana"
    )
    assert venta.fecha_local == "2026-11-10"
    assert venta.fecha_hora_utc.startswith("2026-11-11")
    assert local_date(momento_utc).isoformat() == "2026-11-10"
