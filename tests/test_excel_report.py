"""El Excel exportado debe coincidir AL PESO con `core/analytics.py`."""
from __future__ import annotations

import io
from datetime import date

import openpyxl

from core.analytics import kpis_hoy, kpis_mes
from core.excel_report import exportar_periodo_excel
from core.money import format_cop
from core.permissions import ADMIN, VENDEDOR
from tests.fixtures_analytics import construir_storage, item, producto, stock_fila, venta

HOY = date(2026, 11, 10)


def _storage_tipica():
    return construir_storage(
        ventas=[
            venta(
                "V1",
                "2026-11-0001",
                "2026-11-10T15:00:00+00:00",
                "2026-11-10",
                subtotal=100_000,
                envio_cobrado=8_000,
                descuento_total=5_000,
                total=103_000,
            )
        ],
        venta_items=[
            item("I1", "V1", "P1", "Bolso rosa", cantidad=2, precio_unitario=50_000, costo_unitario=18_000, descuento_linea=5_000, total_linea=95_000),
        ],
        productos=[producto("P1", "Bolso rosa", costo=18_000, precio=55_000)],
        stock=[stock_fila("P1", 7)],
    )


def _leer_resumen(contenido: bytes) -> dict[str, object]:
    wb = openpyxl.load_workbook(io.BytesIO(contenido))
    ws = wb["Resumen"]
    valores = {}
    fila = 4
    while ws.cell(row=fila, column=1).value is not None:
        clave = ws.cell(row=fila, column=1).value
        valor = ws.cell(row=fila, column=2).value
        valores[clave] = valor
        fila += 1
    return valores


def test_excel_dia_coincide_al_peso_con_kpis_hoy_admin():
    storage = _storage_tipica()
    kpis = kpis_hoy(storage, HOY, ADMIN)
    contenido = exportar_periodo_excel(storage, "dia", HOY, ADMIN)
    resumen = _leer_resumen(contenido)

    assert resumen["Ventas netas"] == format_cop(kpis["ventas_netas"])
    assert resumen["Tickets"] == kpis["tickets"]
    assert resumen["Unidades"] == kpis["unidades"]
    assert resumen["Ticket promedio"] == kpis["ticket_promedio_fmt"]
    assert resumen["Descuentos otorgados"] == format_cop(kpis["descuentos_otorgados"])
    assert resumen["Envíos cobrados (aparte)"] == format_cop(kpis["envios_cobrados"])
    assert resumen["Devoluciones (valor)"] == format_cop(kpis["devoluciones_valor"])
    assert resumen["Costo de lo vendido"] == format_cop(kpis["costo_vendido"])
    assert resumen["Ganancia"] == format_cop(kpis["ganancia"])
    assert resumen["Margen %"] == kpis["margen_pct"]


def test_excel_vendedor_no_incluye_filas_de_costo_ni_ganancia():
    storage = _storage_tipica()
    contenido = exportar_periodo_excel(storage, "dia", HOY, VENDEDOR)
    resumen = _leer_resumen(contenido)
    assert "Costo de lo vendido" not in resumen
    assert "Ganancia" not in resumen
    assert "Margen %" not in resumen
    assert resumen["Ventas netas"] == format_cop(95_000)


def test_excel_mes_coincide_al_peso_con_kpis_mes():
    storage = _storage_tipica()
    kpis = kpis_mes(storage, HOY, ADMIN)
    contenido = exportar_periodo_excel(storage, "mes", HOY, ADMIN)
    resumen = _leer_resumen(contenido)
    assert resumen["Ventas netas"] == format_cop(kpis["ventas_netas"])
    assert resumen["Ganancia"] == format_cop(kpis["ganancia"])


def test_excel_tiene_las_6_hojas_exactas():
    storage = _storage_tipica()
    contenido = exportar_periodo_excel(storage, "dia", HOY, ADMIN)
    wb = openpyxl.load_workbook(io.BytesIO(contenido))
    assert wb.sheetnames == ["Resumen", "Ventas", "Productos vendidos", "Pagos", "Devoluciones", "Inventario actual"]


def test_excel_hoja_inventario_actual_coincide_con_valor_inventario():
    storage = _storage_tipica()
    from core.analytics import valor_inventario

    inv = valor_inventario(storage)
    contenido = exportar_periodo_excel(storage, "dia", HOY, ADMIN)
    wb = openpyxl.load_workbook(io.BytesIO(contenido))
    ws = wb["Inventario actual"]

    fila_total = None
    for fila in ws.iter_rows(min_row=2):
        if fila[0].value == "TOTAL":
            fila_total = fila
            break
    assert fila_total is not None
    assert fila_total[6].value == inv["al_costo"]
    assert fila_total[7].value == inv["al_precio"]


def test_excel_texto_con_formula_no_se_interpreta():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", cliente_nombre="=1+1", total=0)],
    )
    contenido = exportar_periodo_excel(storage, "dia", HOY, ADMIN)
    wb = openpyxl.load_workbook(io.BytesIO(contenido))
    ws = wb["Ventas"]
    valores_cliente = [c.value for c in ws["F"] if c.value is not None]
    assert "=1+1" in valores_cliente
