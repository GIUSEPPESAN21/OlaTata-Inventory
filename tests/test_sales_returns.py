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
        "ya_devuelto": {},
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


def test_reembolso_no_pierde_un_peso_por_division_float_en_linea_de_14_unidades(storage):
    """Regresión del hallazgo CRÍTICO de V1 (revisor dinero y tiempo): R1
    exige que el dinero NUNCA pase por `float`. `(total_linea_original /
    cantidad_original) * cantidad` con enteros de Python YA es división
    float antes de llegar a `round_half_up_pesos` — con una línea de 14
    unidades (`total_linea=115`) y devolución parcial de 7, el valor
    exacto es 115*7/14 = 57.5 (redondeo mitad arriba = 58), pero el
    camino por `float` binario daba 57.499999999999986 -> redondeaba a 57."""
    venta_resuelta = {
        "numero": "2026-02-0007",
        "items": [
            {
                "producto_id": "P-1",
                "nombre_snapshot": "Bolso Negro",
                "cantidad": 14,
                "precio_unitario": 10,
                "costo_unitario": 1,
                "total_linea": 115,
            }
        ],
        "ya_devuelto": {},
    }
    _seed_producto(storage, stock=20)
    dev = registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta_resuelta,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 7, "destino": "stock"}],
        tipo="devolucion",
        motivo="Prueba de precisión de redondeo",
        reembolso_metodo="efectivo",
    )
    assert dev.reembolso_monto == 58


def test_venta_ya_resuelta_sin_ya_devuelto_declarado_falla_claro(storage):
    """Regresión del hallazgo CRÍTICO de V2 (revisor de atomicidad):
    antes de este fix, una venta de un mes archivado (pasada como dict)
    NUNCA declaraba cuánto se le había devuelto antes del cierre —
    `ya_devuelto_previo` solo consultaba la hoja DEVOLUCIONES del libro
    VIVO, que el cierre de mes vacía. Ahora el dict debe declarar
    'ya_devuelto' explícitamente o la función rechaza la llamada, en vez
    de asumir en silencio que no hubo devoluciones previas."""
    venta_sin_declarar = {
        "numero": "2026-01-0099",
        "items": [
            {
                "producto_id": "P-1",
                "nombre_snapshot": "Bolso Negro",
                "cantidad": 3,
                "precio_unitario": 90_000,
                "costo_unitario": 50_000,
                "total_linea": 270_000,
            }
        ],
        # sin "ya_devuelto": debe rechazarse, no asumir 0 en silencio.
    }
    _seed_producto(storage, stock=5)
    with pytest.raises(DevolucionInvalidaError, match="ya_devuelto"):
        registrar_devolucion_cambio(
            storage,
            VENDEDOR,
            venta_sin_declarar,
            items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
            tipo="devolucion",
            motivo="Sin declarar ya_devuelto",
            reembolso_metodo="efectivo",
        )


def test_venta_archivada_no_permite_devolver_mas_de_lo_que_ya_declara_devuelto(storage):
    """Con `ya_devuelto` correctamente declarado por el llamador (lo que
    debería leer del archivo), una venta de 3 unidades con 2 ya
    devueltas antes del cierre solo deja devolver 1 más — exactamente el
    invariante que el hallazgo de V2 mostró que se podía romper."""
    venta_con_historial = {
        "numero": "2026-01-0100",
        "items": [
            {
                "producto_id": "P-1",
                "nombre_snapshot": "Bolso Negro",
                "cantidad": 3,
                "precio_unitario": 90_000,
                "costo_unitario": 50_000,
                "total_linea": 270_000,
            }
        ],
        "ya_devuelto": {"P-1": 2},
    }
    _seed_producto(storage, stock=5)

    # La unidad restante (1) sí se puede devolver.
    dev = registrar_devolucion_cambio(
        storage,
        VENDEDOR,
        venta_con_historial,
        items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
        tipo="devolucion",
        motivo="Última unidad disponible",
        reembolso_metodo="efectivo",
    )
    assert dev.reembolso_monto == 90_000

    # Pedir una unidad MÁS (ya no queda ninguna: 3 vendidas - 2 - 1 = 0) falla.
    with pytest.raises(DevolucionInvalidaError, match="disponibles"):
        registrar_devolucion_cambio(
            storage,
            VENDEDOR,
            venta_con_historial,
            items_devueltos=[{"producto_id": "P-1", "cantidad": 1, "destino": "stock"}],
            tipo="devolucion",
            motivo="Ya no debería quedar nada",
            reembolso_metodo="efectivo",
        )
