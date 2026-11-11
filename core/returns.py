"""Anulación de ventas y devoluciones/cambios (R9). Propiedad de A2.

Igual que `core.sales`: no depende de `core.inventory`/`core.costing`
(no existen aún en esta rama) — actualiza `STOCK` y `MOVIMIENTOS` directo
vía `storage`, dentro de la misma `transaction()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core import schema
from core.excel_safe import excel_safe
from core.money import round_half_up_pesos
from core.permissions import requerir
from core.timeutil import local_date, now_utc, to_iso_utc

__all__ = [
    "VentaNoEncontradaError",
    "DevolucionInvalidaError",
    "Devolucion",
    "anular_venta",
    "registrar_devolucion_cambio",
]

# Vocabularios propios de este módulo (no están en `core.schema`, que es
# un contrato congelado; si se necesitan como constantes compartidas,
# pedirlo en el informe final).
TIPOS_DEVOLUCION = {"devolucion", "cambio"}
DESTINOS_ITEM_DEVUELTO = {"stock", "merma"}


class VentaNoEncontradaError(ValueError):
    """La venta referenciada no está en el libro vivo (puede estar en un
    mes ya archivado; en ese caso el llamador debe resolverla por su
    cuenta en modo solo lectura y pasar el objeto ya resuelto)."""


class DevolucionInvalidaError(ValueError):
    """La anulación o la devolución no cumple una regla de negocio (R9)."""


@dataclass(frozen=True)
class Devolucion:
    id: str
    numero: str
    venta_numero: str
    fecha_hora_utc: str
    fecha_local: str
    tipo: str
    motivo: str
    reembolso_metodo: str
    reembolso_monto: int
    usuario_id: str
    items: list[dict] = field(default_factory=list)


def anular_venta(storage, rol: str, numero_venta: str, motivo: str, usuario_id: str = "") -> None:
    """R9: SOLO admin (`requerir(rol, "anular_venta")`), motivo
    obligatorio. La venta NO se borra: queda `estado="anulada"` y repone
    stock con un movimiento `"anulacion"`. Idempotente: anular una venta
    ya anulada no vuelve a reponer stock."""
    requerir(rol, "anular_venta")
    motivo_seguro = excel_safe(motivo, field_name="motivo")
    if not motivo_seguro:
        raise DevolucionInvalidaError("El motivo de anulación es obligatorio.")

    with storage.transaction() as tx:
        ventas_df = tx.read_sheet(schema.VENTAS)
        coincide = ventas_df["numero"] == numero_venta
        if not coincide.any():
            raise VentaNoEncontradaError(f"Venta '{numero_venta}' no existe.")
        fila_venta = ventas_df[coincide].iloc[0]
        if fila_venta["estado"] == "anulada":
            return  # idempotente: ya estaba anulada, no se repite la reposición
        if fila_venta["estado"] != "completada":
            raise DevolucionInvalidaError(f"Venta '{numero_venta}' está en estado '{fila_venta['estado']}'.")

        venta_id = fila_venta["id"]
        sede_id = str(fila_venta["sede_id"]) or schema.SEDE_PRINCIPAL
        items_df = tx.read_sheet(schema.VENTA_ITEMS)
        items_venta = items_df[items_df["venta_id"] == venta_id]

        stock_df = tx.read_sheet(schema.STOCK)
        movimientos_df = tx.read_sheet(schema.MOVIMIENTOS)
        ahora_iso = to_iso_utc(now_utc())

        nuevos_movimientos = []
        for _, item in items_venta.iterrows():
            producto_id = str(item["producto_id"])
            cantidad = int(item["cantidad"])

            coincide_stock = (stock_df["producto_id"] == producto_id) & (stock_df["sede_id"] == sede_id)
            stock_antes = int(stock_df.loc[coincide_stock, "cantidad"].iloc[0]) if coincide_stock.any() else 0
            stock_despues = stock_antes + cantidad

            if coincide_stock.any():
                stock_df.loc[coincide_stock, "cantidad"] = stock_despues
                stock_df.loc[coincide_stock, "updated_at"] = ahora_iso
            else:
                nueva_fila = pd.DataFrame(
                    [
                        {
                            "producto_id": producto_id,
                            "sede_id": sede_id,
                            "cantidad": stock_despues,
                            "created_at": ahora_iso,
                            "updated_at": ahora_iso,
                        }
                    ]
                )
                stock_df = pd.concat([stock_df, nueva_fila], ignore_index=True)

            costo_unitario = 0 if pd.isna(item["costo_unitario"]) else int(item["costo_unitario"])
            mov_id = f"M-{tx.next_counter('movimientos'):06d}"
            nuevos_movimientos.append(
                {
                    "id": mov_id,
                    "fecha_hora_utc": ahora_iso,
                    "producto_id": producto_id,
                    "sede_id": sede_id,
                    "tipo": "anulacion",
                    "cantidad": cantidad,
                    "stock_antes": stock_antes,
                    "stock_despues": stock_despues,
                    "costo_unitario": costo_unitario,
                    "ref_tipo": "venta",
                    "ref_id": venta_id,
                    "proveedor_id": "",
                    "documento_ref": numero_venta,
                    "usuario_id": usuario_id,
                    "nota": motivo_seguro,
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            )

        tx.write_sheet(schema.STOCK, stock_df)
        tx.write_sheet(
            schema.MOVIMIENTOS, pd.concat([movimientos_df, pd.DataFrame(nuevos_movimientos)], ignore_index=True)
        )

        ventas_df.loc[coincide, "estado"] = "anulada"
        ventas_df.loc[coincide, "anulada_por"] = usuario_id
        ventas_df.loc[coincide, "anulada_motivo"] = motivo_seguro
        ventas_df.loc[coincide, "anulada_at"] = ahora_iso
        ventas_df.loc[coincide, "updated_at"] = ahora_iso
        tx.write_sheet(schema.VENTAS, ventas_df)


def _resolver_venta_e_items(storage, venta) -> tuple[str, list[dict]]:
    """`venta` puede ser:

    - un `numero` (str): se busca en `VENTAS`/`VENTA_ITEMS` VIVAS.
    - un objeto ya resuelto (dict con `"numero"`/`"items"`, o
      `core.sales.Venta`): usado directo, sin tocar storage para esa
      parte — así una venta de un mes ya archivado (consultada aparte en
      modo solo lectura) puede devolverse igual (R9).
    """
    if isinstance(venta, str):
        ventas_df = storage.read_sheet(schema.VENTAS)
        fila_df = ventas_df[ventas_df["numero"] == venta]
        if fila_df.empty:
            raise VentaNoEncontradaError(
                f"Venta '{venta}' no está en el libro vivo. Si es de un mes archivado, "
                "resuélvela en modo solo lectura y pasa el objeto ya resuelto en vez del número."
            )
        venta_id = fila_df.iloc[0]["id"]
        items_df = storage.read_sheet(schema.VENTA_ITEMS)
        items = items_df[items_df["venta_id"] == venta_id].to_dict("records")
        return venta, items
    if isinstance(venta, dict):
        return venta["numero"], list(venta["items"])
    return venta.numero, list(venta.items)


def registrar_devolucion_cambio(
    storage,
    rol: str,
    venta,
    items_devueltos: list[dict],
    tipo: str,
    motivo: str,
    reembolso_metodo: str,
    usuario_id: str = "",
) -> Devolucion:
    """R9: vendedor o admin (`requerir(rol, "devolucion_cambio")`). Valida
    `cantidad devuelta <= vendido - ya_devuelto`. Repone a stock salvo que
    el item traiga `destino="merma"` (dañado: no entra a stock). Resta en
    la `fecha_local` de HOY, nunca en la de la venta original. Si
    `reembolso_metodo == "cambio"` queda registrado como saldo a favor
    (ver limitación en el informe final: no hay hoja de saldos en el
    esquema congelado, así que "aplicarlo" a una venta nueva es un
    proceso manual/futuro, no automático en M1)."""
    requerir(rol, "devolucion_cambio")
    if tipo not in TIPOS_DEVOLUCION:
        raise DevolucionInvalidaError(f"Tipo de devolución inválido: {tipo!r}.")
    if reembolso_metodo not in schema.METODOS_PAGO:
        raise DevolucionInvalidaError(f"Método de reembolso inválido: {reembolso_metodo!r}.")
    motivo_seguro = excel_safe(motivo, field_name="motivo")
    if not motivo_seguro:
        raise DevolucionInvalidaError("El motivo de la devolución es obligatorio.")
    if not items_devueltos:
        raise DevolucionInvalidaError("La devolución no tiene productos.")

    venta_numero, items_venta_originales = _resolver_venta_e_items(storage, venta)
    items_por_producto = {str(it["producto_id"]): it for it in items_venta_originales}

    with storage.transaction() as tx:
        devoluciones_df = tx.read_sheet(schema.DEVOLUCIONES)
        devolucion_items_df = tx.read_sheet(schema.DEVOLUCION_ITEMS)

        ya_devuelto_previo = devolucion_items_df.merge(
            devoluciones_df[["id", "venta_numero"]],
            left_on="devolucion_id",
            right_on="id",
            suffixes=("", "_cab"),
        )
        ya_devuelto_previo = ya_devuelto_previo[ya_devuelto_previo["venta_numero"] == venta_numero]

        stock_df = tx.read_sheet(schema.STOCK)
        movimientos_df = tx.read_sheet(schema.MOVIMIENTOS)

        ahora = now_utc()
        ahora_iso = to_iso_utc(ahora)
        fecha_local_hoy = local_date(ahora)
        fecha_local_iso = fecha_local_hoy.isoformat()
        año_mes = f"{fecha_local_hoy.year:04d}-{fecha_local_hoy.month:02d}"

        reembolso_total = 0
        filas_items_devolucion: list[dict] = []
        nuevos_movimientos: list[dict] = []

        for item_dev in items_devueltos:
            producto_id = str(item_dev["producto_id"])
            cantidad = int(item_dev["cantidad"])
            destino = str(item_dev.get("destino", "stock"))
            if destino not in DESTINOS_ITEM_DEVUELTO:
                raise DevolucionInvalidaError(f"Destino inválido: {destino!r}.")
            if cantidad <= 0:
                raise DevolucionInvalidaError(f"Cantidad inválida para '{producto_id}': {cantidad}.")

            original = items_por_producto.get(producto_id)
            if original is None:
                raise DevolucionInvalidaError(f"'{producto_id}' no está en la venta '{venta_numero}'.")

            cantidad_vendida = int(original["cantidad"])
            ya_devuelto = int(
                ya_devuelto_previo.loc[ya_devuelto_previo["producto_id"] == producto_id, "cantidad"].sum()
            )
            disponible_para_devolver = cantidad_vendida - ya_devuelto
            if cantidad > disponible_para_devolver:
                raise DevolucionInvalidaError(
                    f"'{producto_id}': se pide devolver {cantidad}, pero solo quedan "
                    f"{disponible_para_devolver} disponibles (vendido={cantidad_vendida}, "
                    f"ya_devuelto={ya_devuelto})."
                )

            precio_unitario = int(original["precio_unitario"])
            costo_unitario = int(original["costo_unitario"])
            cantidad_original = cantidad_vendida or 1
            total_linea_original = int(original["total_linea"])
            monto_item = round_half_up_pesos((total_linea_original / cantidad_original) * cantidad)
            reembolso_total += monto_item

            dev_item_id = f"DI-{tx.next_counter('devolucion_items'):06d}"
            filas_items_devolucion.append(
                {
                    "id": dev_item_id,
                    "devolucion_id": None,  # se completa tras crear la cabecera
                    "producto_id": producto_id,
                    "nombre_snapshot": excel_safe(
                        original.get("nombre_snapshot", "") or "", field_name="nombre_snapshot"
                    ),
                    "cantidad": cantidad,
                    "precio_unitario": precio_unitario,
                    "costo_unitario": costo_unitario,
                    "destino": destino,
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            )

            if destino == "stock":
                sede_id = schema.SEDE_PRINCIPAL
                coincide_stock = (stock_df["producto_id"] == producto_id) & (stock_df["sede_id"] == sede_id)
                stock_antes = int(stock_df.loc[coincide_stock, "cantidad"].iloc[0]) if coincide_stock.any() else 0
                stock_despues = stock_antes + cantidad
                if coincide_stock.any():
                    stock_df.loc[coincide_stock, "cantidad"] = stock_despues
                    stock_df.loc[coincide_stock, "updated_at"] = ahora_iso
                else:
                    nueva_fila = pd.DataFrame(
                        [
                            {
                                "producto_id": producto_id,
                                "sede_id": sede_id,
                                "cantidad": stock_despues,
                                "created_at": ahora_iso,
                                "updated_at": ahora_iso,
                            }
                        ]
                    )
                    stock_df = pd.concat([stock_df, nueva_fila], ignore_index=True)

                mov_id = f"M-{tx.next_counter('movimientos'):06d}"
                nuevos_movimientos.append(
                    {
                        "id": mov_id,
                        # R9: resta en el día en que se hace, NO en el de la venta original.
                        "fecha_hora_utc": ahora_iso,
                        "producto_id": producto_id,
                        "sede_id": sede_id,
                        "tipo": "devolucion",
                        "cantidad": cantidad,
                        "stock_antes": stock_antes,
                        "stock_despues": stock_despues,
                        "costo_unitario": costo_unitario,
                        "ref_tipo": "devolucion",
                        "ref_id": "",  # se completa tras crear la cabecera
                        "proveedor_id": "",
                        "documento_ref": venta_numero,
                        "usuario_id": usuario_id,
                        "nota": motivo_seguro,
                        "created_at": ahora_iso,
                        "updated_at": ahora_iso,
                    }
                )
            # destino == "merma": dañado, no entra a stock -> ninguna
            # variación de stock, por eso no se genera movimiento (R4:
            # "toda VARIACIÓN de stock..." — aquí no hay ninguna).

        numero_devolucion = f"{año_mes}-{tx.next_counter('devoluciones', reset_key=año_mes):04d}"
        devolucion_id = f"DV-{tx.next_counter('devoluciones_id'):06d}"

        for fila in filas_items_devolucion:
            fila["devolucion_id"] = devolucion_id
        for mov in nuevos_movimientos:
            mov["ref_id"] = devolucion_id

        nueva_devolucion = pd.DataFrame(
            [
                {
                    "id": devolucion_id,
                    "numero": numero_devolucion,
                    "venta_numero": venta_numero,
                    "fecha_hora_utc": ahora_iso,
                    "fecha_local": fecha_local_iso,
                    "tipo": tipo,
                    "motivo": motivo_seguro,
                    "reembolso_metodo": reembolso_metodo,
                    "reembolso_monto": reembolso_total,
                    "usuario_id": usuario_id,
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            ]
        )
        tx.write_sheet(schema.DEVOLUCIONES, pd.concat([devoluciones_df, nueva_devolucion], ignore_index=True))
        tx.write_sheet(
            schema.DEVOLUCION_ITEMS,
            pd.concat([devolucion_items_df, pd.DataFrame(filas_items_devolucion)], ignore_index=True),
        )
        if nuevos_movimientos:
            tx.write_sheet(
                schema.MOVIMIENTOS, pd.concat([movimientos_df, pd.DataFrame(nuevos_movimientos)], ignore_index=True)
            )
        tx.write_sheet(schema.STOCK, stock_df)

        return Devolucion(
            id=devolucion_id,
            numero=numero_devolucion,
            venta_numero=venta_numero,
            fecha_hora_utc=ahora_iso,
            fecha_local=fecha_local_iso,
            tipo=tipo,
            motivo=motivo_seguro,
            reembolso_metodo=reembolso_metodo,
            reembolso_monto=reembolso_total,
            usuario_id=usuario_id,
            items=filas_items_devolucion,
        )
