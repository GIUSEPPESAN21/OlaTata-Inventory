"""Costeo de inventario: costo promedio ponderado (R5) y registro de
entradas de mercancía.

Propiedad exclusiva de A1 (INVENTARIO). No es un contrato congelado — ver
docs/CONTRATOS.md para la lista de módulos que SÍ lo son.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from core import schema
from core.excel_safe import excel_safe
from core.money import parse_pesos, round_half_up_pesos
from core.permissions import requerir
from core.timeutil import now_utc, to_iso_utc

__all__ = ["costo_promedio_ponderado", "registrar_entrada"]


def costo_promedio_ponderado(
    stock_prev: int, costo_prev: int, cantidad_entrada: int, costo_entrada: int
) -> int:
    """Costo promedio ponderado tras una entrada de mercancía (R5).

    ``nuevo_costo = (stock_prev*costo_prev + cantidad_entrada*costo_entrada)
    / (stock_prev + cantidad_entrada)``, redondeado a peso entero (mitad
    hacia arriba). Caso de borde: si ``stock_prev <= 0`` (sin stock previo,
    o un valor corrupto negativo) se usa directamente ``costo_entrada``, sin
    promediar con un stock que no existe.
    """
    cantidad_entrada = int(cantidad_entrada)
    if cantidad_entrada <= 0:
        raise ValueError("La cantidad de entrada debe ser mayor que cero.")
    costo_entrada = int(costo_entrada)
    if costo_entrada < 0:
        raise ValueError("El costo de entrada no puede ser negativo.")

    stock_prev = int(stock_prev)
    costo_prev = int(costo_prev)
    if stock_prev <= 0:
        return costo_entrada

    numerador = Decimal(stock_prev) * Decimal(costo_prev) + Decimal(cantidad_entrada) * Decimal(
        costo_entrada
    )
    denominador = Decimal(stock_prev + cantidad_entrada)
    return round_half_up_pesos(numerador / denominador)


def registrar_entrada(
    storage,
    rol: str,
    *,
    producto_id: str,
    cantidad: int,
    costo_unitario,
    usuario_id: str,
    sede_id: str = schema.SEDE_PRINCIPAL,
    proveedor_id: str | None = None,
    documento_ref: str | None = None,
    nota: str | None = None,
) -> dict:
    """Registra una ENTRADA de mercancía (R4, R5): recalcula el costo
    promedio ponderado del producto, actualiza el stock y deja una fila en
    ``movimientos`` con tipo "entrada". Todo dentro de una única
    transacción atómica (`storage.transaction()`).

    Solo admin (capacidad "ajustar_stock", revalidada aquí, no solo en la
    UI). Lanza `PermisoDenegadoError` si el rol no tiene la capacidad.
    """
    requerir(rol, "ajustar_stock")

    cantidad = int(cantidad)
    if cantidad <= 0:
        raise ValueError("La cantidad de entrada debe ser mayor que cero.")
    costo_unitario = parse_pesos(costo_unitario)
    if costo_unitario < 0:
        raise ValueError("El costo unitario no puede ser negativo.")

    documento_ref_safe = excel_safe(documento_ref or "", field_name="documento_ref")
    nota_safe = excel_safe(nota or "", field_name="nota")
    proveedor_id_safe = excel_safe(proveedor_id or "", field_name="proveedor_id")

    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        coincide_prod = productos["id"] == producto_id
        if not coincide_prod.any():
            raise ValueError(f"El producto '{producto_id}' no existe.")

        stock_df = tx.read_sheet(schema.STOCK)
        coincide_stock = (stock_df["producto_id"] == producto_id) & (stock_df["sede_id"] == sede_id)

        stock_prev = int(stock_df.loc[coincide_stock, "cantidad"].iloc[0]) if coincide_stock.any() else 0
        costo_previo_raw = productos.loc[coincide_prod, "costo"].iloc[0]
        costo_prev = 0 if pd.isna(costo_previo_raw) else int(costo_previo_raw)

        nuevo_costo = costo_promedio_ponderado(stock_prev, costo_prev, cantidad, costo_unitario)
        stock_nuevo = stock_prev + cantidad

        ahora = to_iso_utc(now_utc())
        productos.loc[coincide_prod, "costo"] = nuevo_costo
        productos.loc[coincide_prod, "updated_at"] = ahora
        tx.write_sheet(schema.PRODUCTOS, productos)

        if coincide_stock.any():
            stock_df.loc[coincide_stock, "cantidad"] = stock_nuevo
            stock_df.loc[coincide_stock, "updated_at"] = ahora
        else:
            nueva_fila_stock = pd.DataFrame(
                [
                    {
                        "producto_id": producto_id,
                        "sede_id": sede_id,
                        "cantidad": stock_nuevo,
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                ]
            )
            stock_df = pd.concat([stock_df, nueva_fila_stock], ignore_index=True)
        tx.write_sheet(schema.STOCK, stock_df)

        mov_id = f"MOV-{tx.next_counter('movimientos'):08d}"
        movimientos = tx.read_sheet(schema.MOVIMIENTOS)
        nuevo_mov = pd.DataFrame(
            [
                {
                    "id": mov_id,
                    "fecha_hora_utc": ahora,
                    "producto_id": producto_id,
                    "sede_id": sede_id,
                    "tipo": "entrada",
                    "cantidad": cantidad,
                    "stock_antes": stock_prev,
                    "stock_despues": stock_nuevo,
                    "costo_unitario": costo_unitario,
                    "ref_tipo": "entrada_mercancia",
                    "ref_id": mov_id,
                    "proveedor_id": proveedor_id_safe,
                    "documento_ref": documento_ref_safe,
                    "usuario_id": usuario_id,
                    "nota": nota_safe,
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            ]
        )
        tx.write_sheet(schema.MOVIMIENTOS, pd.concat([movimientos, nuevo_mov], ignore_index=True))

    return {
        "producto_id": producto_id,
        "costo_anterior": costo_prev,
        "costo_nuevo": nuevo_costo,
        "stock_anterior": stock_prev,
        "stock_nuevo": stock_nuevo,
        "movimiento_id": mov_id,
    }
