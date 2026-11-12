"""Exporta un periodo (día/semana/mes) a `.xlsx` con 6 hojas (§7):

Resumen · Ventas · Productos vendidos · Pagos · Devoluciones ·
Inventario actual — con la paleta de marca de Ola Tata (primario
`#C2185B`, dorado `#C09860`) en los encabezados.

Los totales de este Excel DEBEN coincidir AL PESO con lo que calcula
`core/analytics.py` para el MISMO periodo: no se reimplementan las
fórmulas aquí, se REUSAN las funciones de `core.analytics` como única
fuente de verdad (ver prueba `tests/test_excel_report.py`).

CONTRATO CONGELADO (ver docs/CONTRATOS.md): este módulo NUNCA modifica
`core/schema.py`, `core/money.py`, `core/timeutil.py`, `core/storage.py`
ni `core/permissions.py` — solo los importa. Usa `openpyxl` directo
(no `fastxlsx`, aún no disponible — ver docs/CONTRATOS.md).
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core import schema
from core.analytics import (
    _cargar_periodo,
    _filtrar_periodo,
    dia_bounds_utc,
    kpis_hoy,
    kpis_mes,
    kpis_semana,
    valor_inventario,
)
from core.excel_safe import excel_safe
from core.money import format_cop
from core.permissions import tiene_capacidad
from core.timeutil import week_bounds_utc

__all__ = ["exportar_periodo_excel"]

_FILL_PRIMARIO = PatternFill(start_color="C2185B", end_color="C2185B", fill_type="solid")
_FILL_DORADO = PatternFill(start_color="C09860", end_color="C09860", fill_type="solid")
_FONT_ENCABEZADO = Font(color="FFFFFF", bold=True)
_FONT_TITULO = Font(color="2B1B22", bold=True, size=14)


def _encabezado(ws, fila: int, columnas: list[str], fill: PatternFill = _FILL_PRIMARIO) -> None:
    for idx, nombre in enumerate(columnas, start=1):
        celda = ws.cell(row=fila, column=idx, value=excel_safe(nombre, field_name="encabezado"))
        celda.fill = fill
        celda.font = _FONT_ENCABEZADO
        celda.alignment = Alignment(horizontal="center")


def _autoajustar(ws, columnas: list[str]) -> None:
    for idx, nombre in enumerate(columnas, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = max(12, len(nombre) + 2)


def _escribir_filas(ws, fila_inicio: int, registros: list[dict[str, Any]], columnas: list[str]) -> None:
    for offset, registro in enumerate(registros):
        for idx, col in enumerate(columnas, start=1):
            valor = registro.get(col)
            if isinstance(valor, str):
                valor = excel_safe(valor, field_name=col)
            ws.cell(row=fila_inicio + offset, column=idx, value=valor)


def _rango_periodo(tipo: Literal["dia", "semana", "mes"], fecha_local: date) -> tuple[datetime, datetime]:
    if tipo == "dia":
        return dia_bounds_utc(fecha_local)
    if tipo == "semana":
        inicio, _ = week_bounds_utc(fecha_local)
        return inicio, dia_bounds_utc(fecha_local)[1]
    if tipo == "mes":
        from core.timeutil import month_bounds_utc

        inicio, _ = month_bounds_utc(fecha_local.year, fecha_local.month)
        return inicio, dia_bounds_utc(fecha_local)[1]
    raise ValueError(f"Tipo de periodo desconocido: {tipo!r}")


def exportar_periodo_excel(
    storage: Any,
    tipo: Literal["dia", "semana", "mes"],
    fecha_local: date,
    rol: str,
    usuario_id: str | None = None,
) -> bytes:
    """Genera el `.xlsx` del periodo pedido. Devuelve los bytes del libro.

    `tipo="dia"` usa `kpis_hoy`, `"semana"` usa `kpis_semana`, `"mes"`
    usa `kpis_mes` — exactamente los mismos números que ve la pantalla
    (misma fuente: `core.analytics`), para que el Excel y la pantalla
    coincidan AL PESO.
    """
    if tipo == "dia":
        kpis = kpis_hoy(storage, fecha_local, rol, usuario_id=usuario_id)
    elif tipo == "semana":
        kpis = kpis_semana(storage, fecha_local, rol, usuario_id=usuario_id)
    elif tipo == "mes":
        kpis = kpis_mes(storage, fecha_local, rol, usuario_id=usuario_id)
    else:
        raise ValueError(f"Tipo de periodo desconocido: {tipo!r}")

    inicio_utc, fin_utc = _rango_periodo(tipo, fecha_local)
    hojas = _cargar_periodo(storage, inicio_utc, fin_utc)
    datos = _filtrar_periodo(hojas, inicio_utc, fin_utc, usuario_id=usuario_id)

    wb = Workbook()
    wb.remove(wb.active)

    _hoja_resumen(wb, tipo, fecha_local, kpis, rol)
    _hoja_ventas(wb, datos.ventas)
    _hoja_productos_vendidos(wb, datos.venta_items, rol)
    _hoja_pagos(wb, datos.pagos)
    _hoja_devoluciones(wb, datos.devoluciones, datos.devolucion_items, rol)
    _hoja_inventario_actual(wb, storage, rol)

    # R11: ninguna celda de texto se guarda jamás como fórmula, sin
    # importar con qué carácter empiece (p.ej. "=1+1") — misma protección
    # que aplica `core/storage.py` al escribir el libro vivo.
    for ws in wb.worksheets:
        for fila in ws.iter_rows():
            for celda in fila:
                if isinstance(celda.value, str):
                    celda.data_type = "s"

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _hoja_resumen(wb, tipo: str, fecha_local: date, kpis: dict[str, Any], rol: str) -> None:
    ws = wb.create_sheet("Resumen")
    ws.cell(row=1, column=1, value=excel_safe(f"Ola Tata — Análisis ({tipo}) — {fecha_local.isoformat()}")).font = _FONT_TITULO

    filas = [
        ("Ventas netas", format_cop(kpis["ventas_netas"])),
        ("Tickets", kpis["tickets"]),
        ("Unidades", kpis["unidades"]),
        ("Ticket promedio", kpis["ticket_promedio_fmt"]),
        ("Descuentos otorgados", format_cop(kpis["descuentos_otorgados"])),
        ("Envíos cobrados (aparte)", format_cop(kpis["envios_cobrados"])),
        ("Devoluciones (valor)", format_cop(kpis["devoluciones_valor"])),
        ("Devoluciones (unidades)", kpis["devoluciones_unidades"]),
    ]
    if tiene_capacidad(rol, "ver_analisis_completo"):
        filas.extend(
            [
                ("Costo de lo vendido", format_cop(kpis["costo_vendido"])),
                ("Ganancia", format_cop(kpis["ganancia"])),
                ("Margen %", kpis["margen_pct"]),
            ]
        )

    _encabezado(ws, 3, ["Indicador", "Valor"], fill=_FILL_DORADO)
    for offset, (nombre, valor) in enumerate(filas, start=4):
        ws.cell(row=offset, column=1, value=excel_safe(nombre, field_name="indicador"))
        ws.cell(row=offset, column=2, value=valor if not isinstance(valor, str) else excel_safe(valor, field_name="valor"))
    _autoajustar(ws, ["Indicador", "Valor del indicador"])


_COLS_VENTAS = [
    "id",
    "numero",
    "fecha_hora_utc",
    "fecha_local",
    "canal",
    "cliente_nombre",
    "subtotal",
    "descuento_total",
    "envio_cobrado",
    "total",
    "estado",
    "vendedor_nombre",
]


def _hoja_ventas(wb, ventas) -> None:
    ws = wb.create_sheet("Ventas")
    _encabezado(ws, 1, _COLS_VENTAS)
    registros = ventas.to_dict("records") if not ventas.empty else []
    _escribir_filas(ws, 2, registros, _COLS_VENTAS)
    _autoajustar(ws, _COLS_VENTAS)


_COLS_ITEMS = [
    "venta_id",
    "producto_id",
    "nombre_snapshot",
    "cantidad",
    "precio_unitario",
    "descuento_linea",
    "costo_unitario",
    "total_linea",
]

# Columnas que revelan costo/margen (R1 §10): un vendedor sin
# "ver_analisis_completo" NUNCA debe verlas, ni en pantalla ni en el
# Excel exportado. Hallazgo ALTO de V3: `_hoja_inventario_actual` ya
# filtraba esto en el Resumen, pero NO aquí ni en "Devoluciones" — un
# vendedor podía exportar y ver costos reales igual.
_COLS_COSTO = {"costo", "costo_unitario", "valor_al_costo"}


def _sin_columnas_de_costo(columnas: list[str], tiene_completo: bool) -> list[str]:
    if tiene_completo:
        return columnas
    return [c for c in columnas if c not in _COLS_COSTO]


def _hoja_productos_vendidos(wb, venta_items, rol: str) -> None:
    tiene_completo = tiene_capacidad(rol, "ver_analisis_completo")
    columnas = _sin_columnas_de_costo(_COLS_ITEMS, tiene_completo)
    ws = wb.create_sheet("Productos vendidos")
    _encabezado(ws, 1, columnas)
    registros = venta_items.to_dict("records") if not venta_items.empty else []
    _escribir_filas(ws, 2, registros, columnas)
    _autoajustar(ws, columnas)


_COLS_PAGOS = ["venta_id", "metodo", "monto", "referencia", "fecha_hora_utc"]


def _hoja_pagos(wb, pagos) -> None:
    ws = wb.create_sheet("Pagos")
    _encabezado(ws, 1, _COLS_PAGOS)
    registros = pagos.to_dict("records") if not pagos.empty else []
    _escribir_filas(ws, 2, registros, _COLS_PAGOS)
    _autoajustar(ws, _COLS_PAGOS)


_COLS_DEVOLUCIONES = ["numero", "venta_numero", "fecha_hora_utc", "tipo", "motivo", "reembolso_metodo", "reembolso_monto"]
_COLS_DEVOLUCION_ITEMS = ["devolucion_id", "producto_id", "nombre_snapshot", "cantidad", "precio_unitario", "costo_unitario", "destino"]


def _hoja_devoluciones(wb, devoluciones, devolucion_items, rol: str) -> None:
    tiene_completo = tiene_capacidad(rol, "ver_analisis_completo")
    columnas_items = _sin_columnas_de_costo(_COLS_DEVOLUCION_ITEMS, tiene_completo)
    ws = wb.create_sheet("Devoluciones")
    _encabezado(ws, 1, _COLS_DEVOLUCIONES)
    registros = devoluciones.to_dict("records") if not devoluciones.empty else []
    _escribir_filas(ws, 2, registros, _COLS_DEVOLUCIONES)

    fila_items = len(registros) + 4
    ws.cell(row=fila_items - 1, column=1, value="Líneas devueltas").font = Font(bold=True)
    _encabezado(ws, fila_items, columnas_items, fill=_FILL_DORADO)
    registros_items = devolucion_items.to_dict("records") if not devolucion_items.empty else []
    _escribir_filas(ws, fila_items + 1, registros_items, columnas_items)
    _autoajustar(ws, _COLS_DEVOLUCIONES)


_COLS_INVENTARIO = ["producto_id", "nombre", "categoria", "stock", "costo", "precio", "valor_al_costo", "valor_al_precio"]


def _hoja_inventario_actual(wb, storage, rol: str) -> None:
    tiene_completo = tiene_capacidad(rol, "ver_analisis_completo")
    columnas = _sin_columnas_de_costo(_COLS_INVENTARIO, tiene_completo)
    ws = wb.create_sheet("Inventario actual")
    _encabezado(ws, 1, columnas)

    productos = storage.read_sheet(schema.PRODUCTOS)
    stock = storage.read_sheet(schema.STOCK)
    totales = {}
    if not stock.empty:
        for _, fila in stock.iterrows():
            pid = fila["producto_id"]
            cantidad = int(fila["cantidad"] or 0)
            totales[pid] = totales.get(pid, 0) + cantidad

    registros = []
    for _, fila in productos.iterrows():
        pid = fila["id"]
        cantidad = int(totales.get(pid, 0))
        costo = int(fila.get("costo") or 0)
        precio = int(fila.get("precio") or 0)
        registros.append(
            {
                "producto_id": pid,
                "nombre": fila.get("nombre"),
                "categoria": fila.get("categoria"),
                "stock": cantidad,
                "costo": costo,
                "precio": precio,
                "valor_al_costo": cantidad * costo,
                "valor_al_precio": cantidad * precio,
            }
        )
    _escribir_filas(ws, 2, registros, columnas)
    _autoajustar(ws, columnas)

    total_costo, total_precio = valor_inventario(storage).values()
    fila_total = len(registros) + 3
    ws.cell(row=fila_total, column=1, value="TOTAL").font = Font(bold=True)
    col_precio = columnas.index("valor_al_precio") + 1
    ws.cell(row=fila_total, column=col_precio, value=total_precio).font = Font(bold=True)
    if tiene_completo:
        col_costo = columnas.index("valor_al_costo") + 1
        ws.cell(row=fila_total, column=col_costo, value=total_costo).font = Font(bold=True)
