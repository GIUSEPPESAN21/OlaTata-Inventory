"""Datos ficticios propios para las pruebas de A3 (ANÁLISIS).

Ningún dato real de referencia: todo lo de aquí es inventado para
probar `core/analytics.py`, `core/cash_close.py` y `core/excel_report.py`
contra las fórmulas EXACTAS de §7. Se apoya en `FakeStorage` de
`tests/conftest.py` (mismo contrato público que `core.storage.Storage`)
y escribe las hojas DENTRO de una transacción, respetando exactamente
las columnas de `core/schema.py`.
"""
from __future__ import annotations

import io
from typing import Any

import openpyxl
import pandas as pd

from core import schema
from tests.conftest import FakeStorage


def _df_desde_filas(nombre_hoja: str, filas: list[dict[str, Any]]) -> pd.DataFrame:
    columnas = schema.columnas(nombre_hoja)
    if not filas:
        return pd.DataFrame(columns=columnas)
    df = pd.DataFrame(filas)
    for col in columnas:
        if col not in df.columns:
            df[col] = None
    return df[columnas].reset_index(drop=True)


def construir_storage(
    *,
    ventas: list[dict] | None = None,
    venta_items: list[dict] | None = None,
    pagos: list[dict] | None = None,
    devoluciones: list[dict] | None = None,
    devolucion_items: list[dict] | None = None,
    movimientos: list[dict] | None = None,
    productos: list[dict] | None = None,
    stock: list[dict] | None = None,
    cuadre_caja: list[dict] | None = None,
) -> FakeStorage:
    """Crea un `FakeStorage` con las hojas dadas, escritas dentro de una
    transacción (igual que haría código de dominio real)."""
    storage = FakeStorage()
    with storage.transaction() as tx:
        tx.write_sheet(schema.VENTAS, _df_desde_filas(schema.VENTAS, ventas or []))
        tx.write_sheet(schema.VENTA_ITEMS, _df_desde_filas(schema.VENTA_ITEMS, venta_items or []))
        tx.write_sheet(schema.PAGOS, _df_desde_filas(schema.PAGOS, pagos or []))
        tx.write_sheet(schema.DEVOLUCIONES, _df_desde_filas(schema.DEVOLUCIONES, devoluciones or []))
        tx.write_sheet(schema.DEVOLUCION_ITEMS, _df_desde_filas(schema.DEVOLUCION_ITEMS, devolucion_items or []))
        tx.write_sheet(schema.MOVIMIENTOS, _df_desde_filas(schema.MOVIMIENTOS, movimientos or []))
        tx.write_sheet(schema.PRODUCTOS, _df_desde_filas(schema.PRODUCTOS, productos or []))
        tx.write_sheet(schema.STOCK, _df_desde_filas(schema.STOCK, stock or []))
        tx.write_sheet(schema.CUADRE_CAJA, _df_desde_filas(schema.CUADRE_CAJA, cuadre_caja or []))
    return storage


def construir_archivo_cierre_bytes(
    *,
    ventas: list[dict] | None = None,
    venta_items: list[dict] | None = None,
    pagos: list[dict] | None = None,
    devoluciones: list[dict] | None = None,
    devolucion_items: list[dict] | None = None,
) -> bytes:
    """Simula el `.xlsx` de un mes YA CERRADO (`cierres/AAAA-MM.xlsx` en
    OlaTata-Archive). Solo escribe las hojas que `core.analytics` lee
    para recomponer un periodo que cruza de mes."""
    hojas = {
        schema.VENTAS: _df_desde_filas(schema.VENTAS, ventas or []),
        schema.VENTA_ITEMS: _df_desde_filas(schema.VENTA_ITEMS, venta_items or []),
        schema.PAGOS: _df_desde_filas(schema.PAGOS, pagos or []),
        schema.DEVOLUCIONES: _df_desde_filas(schema.DEVOLUCIONES, devoluciones or []),
        schema.DEVOLUCION_ITEMS: _df_desde_filas(schema.DEVOLUCION_ITEMS, devolucion_items or []),
    }
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nombre, df in hojas.items():
        ws = wb.create_sheet(title=nombre)
        ws.append(list(df.columns))
        for _, fila in df.iterrows():
            ws.append([None if pd.isna(v) else v for v in fila])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------- constructores
def venta(
    id_: str,
    numero: str,
    fecha_hora_utc: str,
    fecha_local: str,
    *,
    estado: str = "completada",
    canal: str = "tienda",
    subtotal: int = 0,
    descuento_total: int = 0,
    envio_cobrado: int = 0,
    total: int = 0,
    vendedor_id: str = "U-000001",
    vendedor_nombre: str = "Vendedora Uno",
    **extra: Any,
) -> dict[str, Any]:
    fila = {
        "id": id_,
        "numero": numero,
        "fecha_hora_utc": fecha_hora_utc,
        "fecha_local": fecha_local,
        "sede_id": "principal",
        "canal": canal,
        "cliente_nombre": "Cliente de prueba",
        "cliente_telefono": None,
        "subtotal": subtotal,
        "descuento_total": descuento_total,
        "envio_cobrado": envio_cobrado,
        "envio_ciudad": None,
        "envio_transportadora": None,
        "envio_guia": None,
        "total": total,
        "estado": estado,
        "anulada_por": None,
        "anulada_motivo": None,
        "anulada_at": None,
        "vendedor_id": vendedor_id,
        "vendedor_nombre": vendedor_nombre,
        "idempotency_key": f"idem-{id_}",
        "nota": "",
        "created_at": fecha_hora_utc,
        "updated_at": fecha_hora_utc,
    }
    fila.update(extra)
    return fila


def item(
    id_: str,
    venta_id: str,
    producto_id: str,
    nombre_snapshot: str,
    cantidad: int,
    precio_unitario: int,
    costo_unitario: int,
    *,
    descuento_linea: int = 0,
    total_linea: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if total_linea is None:
        total_linea = cantidad * precio_unitario - descuento_linea
    fila = {
        "id": id_,
        "venta_id": venta_id,
        "producto_id": producto_id,
        "nombre_snapshot": nombre_snapshot,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
        "descuento_linea": descuento_linea,
        "costo_unitario": costo_unitario,
        "total_linea": total_linea,
        "created_at": None,
        "updated_at": None,
    }
    fila.update(extra)
    return fila


def pago(id_: str, venta_id: str, metodo: str, monto: int, fecha_hora_utc: str, **extra: Any) -> dict[str, Any]:
    fila = {
        "id": id_,
        "venta_id": venta_id,
        "metodo": metodo,
        "monto": monto,
        "referencia": None,
        "fecha_hora_utc": fecha_hora_utc,
        "created_at": fecha_hora_utc,
        "updated_at": fecha_hora_utc,
    }
    fila.update(extra)
    return fila


def devolucion(
    id_: str,
    numero: str,
    venta_numero: str,
    fecha_hora_utc: str,
    fecha_local: str,
    *,
    tipo: str = "devolucion",
    reembolso_metodo: str = "efectivo",
    reembolso_monto: int = 0,
    **extra: Any,
) -> dict[str, Any]:
    fila = {
        "id": id_,
        "numero": numero,
        "venta_numero": venta_numero,
        "fecha_hora_utc": fecha_hora_utc,
        "fecha_local": fecha_local,
        "tipo": tipo,
        "motivo": "prueba",
        "reembolso_metodo": reembolso_metodo,
        "reembolso_monto": reembolso_monto,
        "usuario_id": "U-000001",
        "created_at": fecha_hora_utc,
        "updated_at": fecha_hora_utc,
    }
    fila.update(extra)
    return fila


def devolucion_item(
    id_: str,
    devolucion_id: str,
    producto_id: str,
    nombre_snapshot: str,
    cantidad: int,
    precio_unitario: int,
    costo_unitario: int,
    *,
    destino: str = "stock",
    **extra: Any,
) -> dict[str, Any]:
    fila = {
        "id": id_,
        "devolucion_id": devolucion_id,
        "producto_id": producto_id,
        "nombre_snapshot": nombre_snapshot,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
        "costo_unitario": costo_unitario,
        "destino": destino,
        "created_at": None,
        "updated_at": None,
    }
    fila.update(extra)
    return fila


def producto(
    id_: str,
    nombre: str,
    *,
    categoria: str = "bolsos",
    costo: int = 0,
    precio: int = 0,
    stock_minimo: int = 2,
    activo: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    fila = {
        "id": id_,
        "nombre": nombre,
        "categoria": categoria,
        "color": None,
        "talla_tamano": None,
        "proveedor_id": None,
        "costo": costo,
        "precio": precio,
        "stock_minimo": stock_minimo,
        "codigo_barras": None,
        "activo": activo,
        "created_at": None,
        "updated_at": None,
    }
    fila.update(extra)
    return fila


def stock_fila(producto_id: str, cantidad: int, *, sede_id: str = "principal", **extra: Any) -> dict[str, Any]:
    fila = {
        "producto_id": producto_id,
        "sede_id": sede_id,
        "cantidad": cantidad,
        "created_at": None,
        "updated_at": None,
    }
    fila.update(extra)
    return fila
