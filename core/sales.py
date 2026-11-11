"""Confirmación de ventas: atómica e idempotente (R1, R3, R6-R8, R10).
Propiedad de A2 (VENTAS).

Diseñado para NO depender de `core.inventory` ni `core.costing` (que aún
no existen en esta rama de trabajo paralelo): lee y escribe `PRODUCTOS`,
`STOCK` y `MOVIMIENTOS` directo vía `storage`, dentro de la misma
`transaction()` que la venta. Si A1 expone funciones equivalentes más
adelante, este módulo puede migrar a ellas sin romper su contrato
público (`confirmar_venta` y el dataclass `Venta`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from core import schema
from core.excel_safe import excel_safe
from core.money import parse_pesos, round_half_up_pesos
from core.permissions import requerir
from core.timeutil import local_date, now_utc, to_iso_utc

__all__ = [
    "Venta",
    "VentaInvalidaError",
    "StockInsuficienteError",
    "PagoInvalidoError",
    "confirmar_venta",
]


class VentaInvalidaError(ValueError):
    """La venta no cumple una regla de negocio (R6, R7, R8)."""


class StockInsuficienteError(VentaInvalidaError):
    """R3: no hay suficiente stock y `permitir_vender_sin_stock` está apagado."""

    def __init__(self, producto_id: str, disponible: int, solicitado: int) -> None:
        self.producto_id = producto_id
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(
            f"Stock insuficiente para '{producto_id}': disponible={disponible}, solicitado={solicitado}."
        )


class PagoInvalidoError(VentaInvalidaError):
    """R6: la suma de los pagos no coincide EXACTO con el total."""


@dataclass(frozen=True)
class Venta:
    """Resultado de `confirmar_venta`. `items`/`pagos` son listas de dict
    (mismas columnas que `VENTA_ITEMS`/`PAGOS`) incluidas por conveniencia
    para que la UI y `core.receipts` no tengan que volver a consultar la
    base."""

    id: str
    numero: str
    fecha_hora_utc: str
    fecha_local: str
    sede_id: str
    canal: str
    cliente_nombre: str
    cliente_telefono: str
    subtotal: int
    descuento_total: int
    envio_cobrado: int
    envio_ciudad: str
    envio_transportadora: str
    envio_guia: str
    total: int
    estado: str
    vendedor_id: str
    vendedor_nombre: str
    idempotency_key: str
    nota: str
    items: list[dict] = field(default_factory=list)
    pagos: list[dict] = field(default_factory=list)


def _resolver_descuento(valor: object, base: int) -> int:
    """`valor` puede ser `None`, un entero en pesos, o
    `{"tipo": "porcentaje"|"monto", "valor": N}`. Nunca devuelve más que
    `base` (R7: "nunca mayor al subtotal") ni un valor negativo."""
    if valor is None:
        return 0
    if isinstance(valor, dict):
        tipo = valor.get("tipo", "monto")
        bruto = valor.get("valor", 0)
        if tipo == "porcentaje":
            pct = Decimal(str(bruto))
            monto = round_half_up_pesos((Decimal(base) * pct) / Decimal(100))
        else:
            monto = parse_pesos(bruto)
    else:
        monto = parse_pesos(valor)
    if monto < 0:
        monto = 0
    return min(monto, base)


def _s(fila, clave: str) -> str:
    valor = fila[clave]
    return "" if pd.isna(valor) else str(valor)


def _fila_a_venta(fila, items: list[dict] | None = None, pagos: list[dict] | None = None) -> Venta:
    return Venta(
        id=_s(fila, "id"),
        numero=_s(fila, "numero"),
        fecha_hora_utc=_s(fila, "fecha_hora_utc"),
        fecha_local=_s(fila, "fecha_local"),
        sede_id=_s(fila, "sede_id"),
        canal=_s(fila, "canal"),
        cliente_nombre=_s(fila, "cliente_nombre"),
        cliente_telefono=_s(fila, "cliente_telefono"),
        subtotal=int(fila["subtotal"]),
        descuento_total=int(fila["descuento_total"]),
        envio_cobrado=int(fila["envio_cobrado"]),
        envio_ciudad=_s(fila, "envio_ciudad"),
        envio_transportadora=_s(fila, "envio_transportadora"),
        envio_guia=_s(fila, "envio_guia"),
        total=int(fila["total"]),
        estado=_s(fila, "estado"),
        vendedor_id=_s(fila, "vendedor_id"),
        vendedor_nombre=_s(fila, "vendedor_nombre"),
        idempotency_key=_s(fila, "idempotency_key"),
        nota=_s(fila, "nota"),
        items=list(items or []),
        pagos=list(pagos or []),
    )


def confirmar_venta(
    storage,
    rol: str,
    idempotency_key: str,
    items: list[dict],
    pagos: list[dict],
    descuento: object = None,
    envio: dict | None = None,
    canal: str = "tienda",
    cliente: dict | None = None,
    vendedor_id: str = "",
    vendedor_nombre: str = "",
    nota: str = "",
) -> Venta:
    """Confirma una venta de forma atómica e idempotente.

    - `requerir(rol, "vender")` primero (§10: revalidado en core/, no solo UI).
    - Si ya existe una venta con `idempotency_key`, la devuelve sin
      duplicar (idempotencia real: la búsqueda ocurre DENTRO de la misma
      transacción con lock, no solo "no reintentar en la UI").
    - Relee stock actual por producto DENTRO de la transacción y rechaza
      si no alcanza (salvo `permitir_vender_sin_stock` en `CONFIG`).
    - Σ pagos debe ser EXACTAMENTE igual al total (R6).
    - Cada línea guarda una foto (snapshot) de nombre/precio/costo del
      momento (R5): cambiar precios después no altera el historial.
    """
    requerir(rol, "vender")

    idempotency_key = (idempotency_key or "").strip()
    if not idempotency_key:
        raise VentaInvalidaError("idempotency_key es obligatoria (R6).")
    if not items:
        raise VentaInvalidaError("La venta no tiene productos.")
    if canal not in schema.CANALES_VENTA:
        raise VentaInvalidaError(f"Canal inválido: {canal!r}.")
    if not pagos:
        raise VentaInvalidaError("La venta no tiene pagos.")
    for pago in pagos:
        if pago.get("metodo") not in schema.METODOS_PAGO:
            raise PagoInvalidoError(f"Método de pago inválido: {pago.get('metodo')!r}.")

    nota_segura = excel_safe(nota, field_name="nota")
    cliente = cliente or {}
    cliente_nombre = excel_safe(cliente.get("nombre", "") or "", field_name="cliente_nombre")
    cliente_telefono = excel_safe(cliente.get("telefono", "") or "", field_name="cliente_telefono")
    envio = envio or {}
    envio_cobrado = parse_pesos(envio.get("cobrado", 0) or 0)
    if envio_cobrado < 0:
        raise VentaInvalidaError("El envío cobrado no puede ser negativo.")
    envio_ciudad = excel_safe(envio.get("ciudad", "") or "", field_name="envio_ciudad")
    envio_transportadora = excel_safe(envio.get("transportadora", "") or "", field_name="envio_transportadora")
    envio_guia = excel_safe(envio.get("guia", "") or "", field_name="envio_guia")
    vendedor_nombre_seguro = excel_safe(vendedor_nombre, field_name="vendedor_nombre")

    with storage.transaction() as tx:
        ventas_df = tx.read_sheet(schema.VENTAS)
        existentes = ventas_df[ventas_df["idempotency_key"] == idempotency_key]
        if not existentes.empty:
            venta_id_existente = existentes.iloc[0]["id"]
            items_existentes_df = tx.read_sheet(schema.VENTA_ITEMS)
            items_existentes = items_existentes_df[items_existentes_df["venta_id"] == venta_id_existente].to_dict(
                "records"
            )
            pagos_existentes_df = tx.read_sheet(schema.PAGOS)
            pagos_existentes = pagos_existentes_df[pagos_existentes_df["venta_id"] == venta_id_existente].to_dict(
                "records"
            )
            return _fila_a_venta(existentes.iloc[0], items_existentes, pagos_existentes)

        permitir_sin_stock = (tx.get_config("permitir_vender_sin_stock", "false") or "false").strip().lower() == "true"

        productos_df = tx.read_sheet(schema.PRODUCTOS)
        stock_df = tx.read_sheet(schema.STOCK)
        movimientos_df = tx.read_sheet(schema.MOVIMIENTOS)

        ahora = now_utc()
        ahora_iso = to_iso_utc(ahora)
        fecha_local_hoy = local_date(ahora)
        fecha_local_iso = fecha_local_hoy.isoformat()

        lineas_calculadas: list[dict] = []
        subtotal = 0
        suma_descuentos_linea = 0
        progreso_stock: dict[tuple[str, str], int] = {}

        for item in items:
            producto_id = str(item["producto_id"])
            cantidad = int(item["cantidad"])
            if cantidad <= 0:
                raise VentaInvalidaError(f"Cantidad inválida para '{producto_id}': {cantidad}.")

            fila_prod_df = productos_df[productos_df["id"] == producto_id]
            if fila_prod_df.empty:
                raise VentaInvalidaError(f"Producto '{producto_id}' no existe.")
            fila_prod = fila_prod_df.iloc[0]

            precio_unitario = parse_pesos(item.get("precio_unitario", fila_prod["precio"]))
            costo_unitario = parse_pesos(item.get("costo_unitario", fila_prod["costo"]))
            nombre_snapshot = excel_safe(
                item.get("nombre_snapshot", fila_prod["nombre"]), field_name="nombre_snapshot"
            )
            sede_id = str(item.get("sede_id") or schema.SEDE_PRINCIPAL)
            clave_stock = (producto_id, sede_id)

            if clave_stock not in progreso_stock:
                fila_stock_df = stock_df[
                    (stock_df["producto_id"] == producto_id) & (stock_df["sede_id"] == sede_id)
                ]
                progreso_stock[clave_stock] = (
                    int(fila_stock_df.iloc[0]["cantidad"]) if not fila_stock_df.empty else 0
                )

            stock_antes = progreso_stock[clave_stock]
            if stock_antes < cantidad and not permitir_sin_stock:
                raise StockInsuficienteError(producto_id, stock_antes, cantidad)
            stock_despues = stock_antes - cantidad
            progreso_stock[clave_stock] = stock_despues

            subtotal_linea = precio_unitario * cantidad
            descuento_linea = _resolver_descuento(
                item.get("descuento_linea", item.get("descuento")), subtotal_linea
            )
            total_linea = subtotal_linea - descuento_linea

            subtotal += subtotal_linea
            suma_descuentos_linea += descuento_linea

            lineas_calculadas.append(
                {
                    "producto_id": producto_id,
                    "sede_id": sede_id,
                    "nombre_snapshot": nombre_snapshot,
                    "cantidad": cantidad,
                    "precio_unitario": precio_unitario,
                    "descuento_linea": descuento_linea,
                    "costo_unitario": costo_unitario,
                    "total_linea": total_linea,
                    "stock_antes": stock_antes,
                    "stock_despues": stock_despues,
                }
            )

        base_descuento_global = subtotal - suma_descuentos_linea
        descuento_global = _resolver_descuento(descuento, base_descuento_global)
        descuento_total = suma_descuentos_linea + descuento_global
        # R7: el envío cobrado va APARTE, nunca cuenta como venta de producto.
        total = subtotal - descuento_total + envio_cobrado

        suma_pagos = sum(parse_pesos(pago.get("monto", 0)) for pago in pagos)
        if suma_pagos != total:
            raise PagoInvalidoError(f"La suma de pagos ({suma_pagos}) no coincide con el total ({total}).")

        año_mes = f"{fecha_local_hoy.year:04d}-{fecha_local_hoy.month:02d}"
        numero = f"{año_mes}-{tx.next_counter('ventas', reset_key=año_mes):04d}"
        venta_id = f"V-{tx.next_counter('ventas_id'):06d}"

        nueva_venta = pd.DataFrame(
            [
                {
                    "id": venta_id,
                    "numero": numero,
                    "fecha_hora_utc": ahora_iso,
                    "fecha_local": fecha_local_iso,
                    "sede_id": schema.SEDE_PRINCIPAL,
                    "canal": canal,
                    "cliente_nombre": cliente_nombre,
                    "cliente_telefono": cliente_telefono,
                    "subtotal": subtotal,
                    "descuento_total": descuento_total,
                    "envio_cobrado": envio_cobrado,
                    "envio_ciudad": envio_ciudad,
                    "envio_transportadora": envio_transportadora,
                    "envio_guia": envio_guia,
                    "total": total,
                    "estado": "completada",
                    "anulada_por": "",
                    "anulada_motivo": "",
                    "anulada_at": "",
                    "vendedor_id": vendedor_id,
                    "vendedor_nombre": vendedor_nombre_seguro,
                    "idempotency_key": idempotency_key,
                    "nota": nota_segura,
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            ]
        )
        tx.write_sheet(schema.VENTAS, pd.concat([ventas_df, nueva_venta], ignore_index=True))

        venta_items_df = tx.read_sheet(schema.VENTA_ITEMS)
        nuevas_filas_items: list[dict] = []
        nuevos_movimientos: list[dict] = []
        for linea in lineas_calculadas:
            item_id = f"VI-{tx.next_counter('venta_items'):06d}"
            nuevas_filas_items.append(
                {
                    "id": item_id,
                    "venta_id": venta_id,
                    "producto_id": linea["producto_id"],
                    "nombre_snapshot": linea["nombre_snapshot"],
                    "cantidad": linea["cantidad"],
                    "precio_unitario": linea["precio_unitario"],
                    "descuento_linea": linea["descuento_linea"],
                    "costo_unitario": linea["costo_unitario"],
                    "total_linea": linea["total_linea"],
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            )
            mov_id = f"M-{tx.next_counter('movimientos'):06d}"
            nuevos_movimientos.append(
                {
                    "id": mov_id,
                    "fecha_hora_utc": ahora_iso,
                    "producto_id": linea["producto_id"],
                    "sede_id": linea["sede_id"],
                    "tipo": "venta",
                    "cantidad": -linea["cantidad"],
                    "stock_antes": linea["stock_antes"],
                    "stock_despues": linea["stock_despues"],
                    "costo_unitario": linea["costo_unitario"],
                    "ref_tipo": "venta",
                    "ref_id": venta_id,
                    "proveedor_id": "",
                    "documento_ref": numero,
                    "usuario_id": vendedor_id,
                    "nota": "",
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            )

        tx.write_sheet(
            schema.VENTA_ITEMS, pd.concat([venta_items_df, pd.DataFrame(nuevas_filas_items)], ignore_index=True)
        )
        tx.write_sheet(
            schema.MOVIMIENTOS, pd.concat([movimientos_df, pd.DataFrame(nuevos_movimientos)], ignore_index=True)
        )

        stock_df_final = tx.read_sheet(schema.STOCK)
        for (producto_id, sede_id), stock_final in progreso_stock.items():
            coincide = (stock_df_final["producto_id"] == producto_id) & (stock_df_final["sede_id"] == sede_id)
            if coincide.any():
                stock_df_final.loc[coincide, "cantidad"] = stock_final
                stock_df_final.loc[coincide, "updated_at"] = ahora_iso
            else:
                nueva_fila_stock = pd.DataFrame(
                    [
                        {
                            "producto_id": producto_id,
                            "sede_id": sede_id,
                            "cantidad": stock_final,
                            "created_at": ahora_iso,
                            "updated_at": ahora_iso,
                        }
                    ]
                )
                stock_df_final = pd.concat([stock_df_final, nueva_fila_stock], ignore_index=True)
        tx.write_sheet(schema.STOCK, stock_df_final)

        pagos_df = tx.read_sheet(schema.PAGOS)
        nuevas_filas_pagos: list[dict] = []
        for pago in pagos:
            pago_id = f"PG-{tx.next_counter('pagos'):06d}"
            nuevas_filas_pagos.append(
                {
                    "id": pago_id,
                    "venta_id": venta_id,
                    "metodo": pago["metodo"],
                    "monto": parse_pesos(pago.get("monto", 0)),
                    "referencia": excel_safe(pago.get("referencia", "") or "", field_name="referencia_pago"),
                    "fecha_hora_utc": ahora_iso,
                    "created_at": ahora_iso,
                    "updated_at": ahora_iso,
                }
            )
        tx.write_sheet(schema.PAGOS, pd.concat([pagos_df, pd.DataFrame(nuevas_filas_pagos)], ignore_index=True))

        return _fila_a_venta(nueva_venta.iloc[0], nuevas_filas_items, nuevas_filas_pagos)
