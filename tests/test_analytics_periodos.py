"""Semana/Mes, cruce de mes vía archivo, desgloses e inventario (§7)."""
from __future__ import annotations

from datetime import date

from core.analytics import (
    kpis_mes,
    kpis_mes_cerrado,
    kpis_semana,
    oraculo_periodo,
    productos_bajo_minimo_y_agotados,
    productos_sin_ventas_en_dias,
    valor_inventario,
    dia_bounds_utc,
)
from core.permissions import ADMIN
from tests.fixtures_analytics import (
    construir_archivo_cierre_bytes,
    construir_storage,
    item,
    producto,
    stock_fila,
    venta,
)


def _storage_semana_cruza_mes():
    # "Hoy" = 1-dic-2026 (martes); la semana inicia el lunes 30-nov-2026,
    # que ya quedó archivado (cerrado) en OlaTata-Archive.
    storage = construir_storage(
        ventas=[venta("V-DEC1", "2026-12-0001", "2026-12-01T15:00:00+00:00", "2026-12-01", total=50_000)],
        venta_items=[item("I-DEC1", "V-DEC1", "P1", "Bolso A", cantidad=1, precio_unitario=50_000, costo_unitario=20_000, total_linea=50_000)],
    )
    archivo_nov = construir_archivo_cierre_bytes(
        ventas=[venta("V-NOV30", "2026-11-0099", "2026-11-30T15:00:00+00:00", "2026-11-30", total=70_000)],
        venta_items=[item("I-NOV30", "V-NOV30", "P1", "Bolso A", cantidad=1, precio_unitario=70_000, costo_unitario=30_000, total_linea=70_000)],
    )
    storage.archive_files["cierres/2026-11.xlsx"] = archivo_nov
    return storage


def test_semana_que_cruza_de_mes_combina_base_viva_y_archivo():
    storage = _storage_semana_cruza_mes()
    kpis = kpis_semana(storage, date(2026, 12, 1), ADMIN)

    assert kpis["ventas_netas"] == 70_000 + 50_000
    assert kpis["tickets"] == 2
    assert kpis["ganancia"] == (70_000 - 30_000) + (50_000 - 20_000)

    fechas = {b["fecha"]: b["ventas_netas"] for b in kpis["barras_por_dia"]}
    assert fechas["2026-11-30"] == 70_000
    assert fechas["2026-12-01"] == 50_000


def test_kpis_mes_cerrado_lee_solo_del_archivo():
    storage = _storage_semana_cruza_mes()
    kpis = kpis_mes_cerrado(storage, 2026, 11, ADMIN)
    assert kpis["ventas_netas"] == 70_000
    assert kpis["tickets"] == 1
    assert kpis["ganancia"] == 70_000 - 30_000


def test_oraculo_coincide_con_kpis_semana_al_peso():
    storage = _storage_semana_cruza_mes()
    kpis = kpis_semana(storage, date(2026, 12, 1), ADMIN)
    inicio_utc, _ = dia_bounds_utc(date(2026, 11, 30))
    _, fin_utc = dia_bounds_utc(date(2026, 12, 1))
    oraculo = oraculo_periodo(storage, inicio_utc, fin_utc)

    assert oraculo["ventas_netas"] == kpis["ventas_netas"]
    assert oraculo["tickets"] == kpis["tickets"]
    assert oraculo["unidades"] == kpis["unidades"]
    assert oraculo["costo_vendido"] == kpis["costo_vendido"]
    assert oraculo["ganancia"] == kpis["ganancia"]
    assert oraculo["margen_pct"] == kpis["margen_pct"]


def test_por_categoria_y_por_canal_del_mes():
    storage = construir_storage(
        ventas=[
            venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", canal="tienda", total=40_000),
            venta("V2", "2026-11-0002", "2026-11-10T16:00:00+00:00", "2026-11-10", canal="instagram", total=25_000),
        ],
        venta_items=[
            item("I1", "V1", "P1", "Bolso A", cantidad=1, precio_unitario=40_000, costo_unitario=15_000, total_linea=40_000),
            item("I2", "V2", "P2", "Correa B", cantidad=1, precio_unitario=25_000, costo_unitario=10_000, total_linea=25_000),
        ],
        productos=[producto("P1", "Bolso A", categoria="bolsos"), producto("P2", "Correa B", categoria="correas")],
    )
    kpis = kpis_mes(storage, date(2026, 11, 10), ADMIN)

    por_canal = {f["canal"]: f["ventas_netas"] for f in kpis["por_canal"]}
    assert por_canal["tienda"] == 40_000
    assert por_canal["instagram"] == 25_000

    por_categoria = {f["categoria"]: f["ventas_netas"] for f in kpis["por_categoria"]}
    assert por_categoria["bolsos"] == 40_000
    assert por_categoria["correas"] == 25_000


def test_top_10_por_unidades_y_por_ganancia():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=0)],
        venta_items=[
            item("I1", "V1", "P1", "Bolso A", cantidad=5, precio_unitario=10_000, costo_unitario=4_000, total_linea=50_000),
            item("I2", "V1", "P2", "Correa B", cantidad=1, precio_unitario=100_000, costo_unitario=10_000, total_linea=100_000),
        ],
    )
    kpis = kpis_mes(storage, date(2026, 11, 10), ADMIN)

    top_unidades = kpis["por_unidades"]
    assert top_unidades[0]["producto_id"] == "P1"
    assert top_unidades[0]["cantidad"] == 5

    top_ganancia = kpis["por_ganancia"]
    assert top_ganancia[0]["producto_id"] == "P2"
    assert top_ganancia[0]["ganancia"] == 100_000 - 10_000


def test_valor_inventario_al_costo_y_al_precio():
    storage = construir_storage(
        productos=[producto("P1", "Bolso A", costo=20_000, precio=50_000), producto("P2", "Correa B", costo=5_000, precio=15_000)],
        stock=[stock_fila("P1", 3), stock_fila("P2", 10)],
    )
    inv = valor_inventario(storage)
    assert inv["al_costo"] == 3 * 20_000 + 10 * 5_000
    assert inv["al_precio"] == 3 * 50_000 + 10 * 15_000


def test_productos_bajo_minimo_y_agotados():
    storage = construir_storage(
        productos=[
            producto("P1", "Bolso A", stock_minimo=5),
            producto("P2", "Correa B", stock_minimo=5),
            producto("P3", "Billetera C", stock_minimo=5),
        ],
        stock=[stock_fila("P1", 0), stock_fila("P2", 3), stock_fila("P3", 20)],
    )
    resultado = productos_bajo_minimo_y_agotados(storage)
    assert resultado["agotados"] == 1  # P1
    assert resultado["bajo_minimo"] == 1  # P2 (3 <= 5)


def test_productos_sin_ventas_en_30_dias():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=10_000)],
        venta_items=[item("I1", "V1", "P1", "Bolso A", cantidad=1, precio_unitario=10_000, costo_unitario=4_000, total_linea=10_000)],
        productos=[producto("P1", "Bolso A"), producto("P2", "Correa B (sin ventas)")],
        stock=[stock_fila("P1", 5), stock_fila("P2", 8)],
    )
    sin_ventas = productos_sin_ventas_en_dias(storage, date(2026, 11, 10), dias=30)
    ids = {f["producto_id"] for f in sin_ventas}
    assert "P2" in ids
    assert "P1" not in ids
