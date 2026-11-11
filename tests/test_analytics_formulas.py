"""Fórmulas EXACTAS de §7 sobre `core/analytics.py` (R1, R5, R7, R9)."""
from __future__ import annotations

from datetime import date

import pytest

from core.analytics import kpis_hoy
from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError
from tests.fixtures_analytics import (
    construir_storage,
    devolucion,
    devolucion_item,
    item,
    venta,
)

HOY = date(2026, 11, 10)


def _hoy_utc(hora: str) -> str:
    return f"2026-11-10T{hora}+00:00"


def test_formulas_basicas_ventas_netas_tickets_unidades_ticket_promedio_ganancia():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=100_000)],
        venta_items=[
            item("I1", "V1", "P1", "Bolso rosa", cantidad=2, precio_unitario=40_000, costo_unitario=15_000, total_linea=80_000),
            item("I2", "V1", "P2", "Correa dorada", cantidad=1, precio_unitario=20_000, costo_unitario=8_000, total_linea=20_000),
        ],
    )
    kpis = kpis_hoy(storage, HOY, ADMIN)

    # Ventas netas = Σ total_linea (sin devoluciones, sin envío).
    assert kpis["ventas_netas"] == 100_000
    assert kpis["tickets"] == 1
    assert kpis["unidades"] == 3
    assert kpis["ticket_promedio"] == 100_000
    assert kpis["ticket_promedio_fmt"] == "$ 100.000"

    # Costo de lo vendido = Σ cantidad×costo_unitario (foto).
    assert kpis["costo_vendido"] == 2 * 15_000 + 1 * 8_000  # 38.000
    # Ganancia = Ventas netas − Costo de lo vendido.
    assert kpis["ganancia"] == 100_000 - 38_000
    # Margen % = Ganancia / Ventas netas.
    assert kpis["margen_pct"] == "62.0%"


def test_margen_es_guion_cuando_no_hay_ventas_en_el_periodo():
    storage = construir_storage()
    kpis = kpis_hoy(storage, HOY, ADMIN)
    assert kpis["ventas_netas"] == 0
    assert kpis["tickets"] == 0
    assert kpis["ticket_promedio"] is None
    assert kpis["ticket_promedio_fmt"] == "—"
    assert kpis["margen_pct"] == "—"
    assert kpis["ganancia"] == 0


def test_envio_cobrado_no_infla_ventas_netas_ni_ganancia():
    storage = construir_storage(
        ventas=[
            venta(
                "V1",
                "2026-11-0001",
                "2026-11-10T15:00:00+00:00",
                "2026-11-10",
                subtotal=100_000,
                envio_cobrado=50_000,
                total=150_000,
            )
        ],
        venta_items=[item("I1", "V1", "P1", "Bolso rosa", cantidad=1, precio_unitario=100_000, costo_unitario=40_000, total_linea=100_000)],
    )
    kpis = kpis_hoy(storage, HOY, ADMIN)
    assert kpis["ventas_netas"] == 100_000  # NO 150.000
    assert kpis["envios_cobrados"] == 50_000
    assert kpis["ganancia"] == 100_000 - 40_000


def test_venta_anulada_se_excluye_de_ventas_netas_y_tickets():
    storage = construir_storage(
        ventas=[
            venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", estado="completada", total=50_000),
            venta("V2", "2026-11-0002", "2026-11-10T16:00:00+00:00", "2026-11-10", estado="anulada", total=999_999),
        ],
        venta_items=[
            item("I1", "V1", "P1", "Bolso rosa", cantidad=1, precio_unitario=50_000, costo_unitario=20_000, total_linea=50_000),
            item("I2", "V2", "P1", "Bolso rosa", cantidad=10, precio_unitario=99_999, costo_unitario=1, total_linea=999_999),
        ],
    )
    kpis = kpis_hoy(storage, HOY, ADMIN)
    assert kpis["ventas_netas"] == 50_000
    assert kpis["tickets"] == 1
    assert kpis["unidades"] == 1


def test_devolucion_resta_en_el_dia_en_que_se_hace_no_en_el_de_la_venta_original():
    # Venta el 5-nov; devolución procesada el 10-nov (R9).
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-05T15:00:00+00:00", "2026-11-05", total=60_000)],
        venta_items=[item("I1", "V1", "P1", "Bolso rosa", cantidad=1, precio_unitario=60_000, costo_unitario=25_000, total_linea=60_000)],
        devoluciones=[devolucion("D1", "DV-0001", "2026-11-0001", "2026-11-10T18:00:00+00:00", "2026-11-10", reembolso_monto=60_000)],
        devolucion_items=[devolucion_item("DI1", "D1", "P1", "Bolso rosa", cantidad=1, precio_unitario=60_000, costo_unitario=25_000, destino="stock")],
    )

    # El día de la VENTA original (5-nov): la devolución NO resta ahí.
    kpis_dia_venta = kpis_hoy(storage, date(2026, 11, 5), ADMIN)
    assert kpis_dia_venta["ventas_netas"] == 60_000
    assert kpis_dia_venta["devoluciones_valor"] == 0

    # El día en que se HIZO la devolución (10-nov): resta ahí.
    kpis_dia_devolucion = kpis_hoy(storage, date(2026, 11, 10), ADMIN)
    assert kpis_dia_devolucion["ventas_netas"] == -60_000  # no hubo ventas ese día, solo la devolución
    assert kpis_dia_devolucion["devoluciones_valor"] == 60_000
    assert kpis_dia_devolucion["devoluciones_unidades"] == 1
    # El costo devuelto SI volvió a stock -> se resta del costo de lo vendido.
    assert kpis_dia_devolucion["costo_vendido"] == -25_000
    assert kpis_dia_devolucion["ganancia"] == -60_000 - (-25_000)


def test_devolucion_con_destino_merma_no_recupera_el_costo():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=0)],
        venta_items=[],
        devoluciones=[devolucion("D1", "DV-0001", "2026-11-0001", "2026-11-10T18:00:00+00:00", "2026-11-10", reembolso_monto=30_000)],
        devolucion_items=[devolucion_item("DI1", "D1", "P1", "Bolso rosa", cantidad=1, precio_unitario=30_000, costo_unitario=12_000, destino="merma")],
    )
    kpis = kpis_hoy(storage, date(2026, 11, 10), ADMIN)
    assert kpis["devoluciones_valor"] == 30_000
    # destino distinto de "stock": el costo NO se recupera.
    assert kpis["costo_vendido"] == 0
    assert kpis["ganancia"] == -30_000


def test_venta_23_30_bogota_cae_en_el_dia_correcto_en_hoy():
    # 23:30 Bogotá del 10-nov == 04:30 UTC del 11-nov (Bogotá es UTC-5).
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-11T04:30:00+00:00", "2026-11-10", total=10_000)],
        venta_items=[item("I1", "V1", "P1", "Bolso rosa", cantidad=1, precio_unitario=10_000, costo_unitario=4_000, total_linea=10_000)],
    )
    kpis_dia_10 = kpis_hoy(storage, date(2026, 11, 10), ADMIN)
    assert kpis_dia_10["ventas_netas"] == 10_000
    assert kpis_dia_10["tickets"] == 1

    kpis_dia_11 = kpis_hoy(storage, date(2026, 11, 11), ADMIN)
    assert kpis_dia_11["ventas_netas"] == 0
    assert kpis_dia_11["tickets"] == 0


def test_vendedor_no_ve_costos_ni_ganancia_ni_margen():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=50_000)],
        venta_items=[item("I1", "V1", "P1", "Bolso rosa", cantidad=1, precio_unitario=50_000, costo_unitario=20_000, total_linea=50_000)],
    )
    kpis = kpis_hoy(storage, HOY, VENDEDOR)
    assert kpis["ventas_netas"] == 50_000
    assert kpis["tickets"] == 1
    assert kpis["unidades"] == 1
    assert "costo_vendido" not in kpis
    assert "ganancia" not in kpis
    assert "margen_pct" not in kpis
    assert "por_ganancia" not in kpis


def test_rol_sin_capacidad_basica_lanza_permiso_denegado():
    storage = construir_storage()
    with pytest.raises(PermisoDenegadoError):
        kpis_hoy(storage, HOY, "fantasma")
