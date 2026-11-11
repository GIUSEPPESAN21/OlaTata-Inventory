"""Cuadre de caja (§7 "HOY"): efectivo esperado vs. contado, diferencia."""
from __future__ import annotations

from datetime import date

import pytest

from core import schema
from core.cash_close import efectivo_esperado_del_dia, registrar_cuadre_caja
from core.permissions import ADMIN, PermisoDenegadoError, VENDEDOR
from tests.fixtures_analytics import construir_storage, devolucion, pago, venta

HOY = date(2026, 11, 10)


def test_efectivo_esperado_suma_pagos_efectivo_y_resta_reembolsos_efectivo():
    storage = construir_storage(
        ventas=[venta("V1", "2026-11-0001", "2026-11-10T15:00:00+00:00", "2026-11-10", total=100_000)],
        pagos=[
            pago("PG1", "V1", "efectivo", 60_000, "2026-11-10T15:00:00+00:00"),
            pago("PG2", "V1", "datafono", 40_000, "2026-11-10T15:00:00+00:00"),
        ],
        devoluciones=[devolucion("D1", "DV-0001", "2026-11-0001", "2026-11-10T17:00:00+00:00", "2026-11-10", reembolso_metodo="efectivo", reembolso_monto=10_000)],
    )
    esperado = efectivo_esperado_del_dia(storage, HOY, base_inicial=50_000)
    # base (50.000) + efectivo (60.000) - reembolso efectivo (10.000) = 100.000
    assert esperado == 100_000


def test_registrar_cuadre_caja_guarda_diferencia():
    storage = construir_storage(
        pagos=[pago("PG1", "V1", "efectivo", 60_000, "2026-11-10T15:00:00+00:00")],
    )
    resultado = registrar_cuadre_caja(storage, ADMIN, HOY, "principal", 50_000, 109_000, "sobra un billete")

    assert resultado["efectivo_esperado"] == 50_000 + 60_000  # 110.000
    assert resultado["efectivo_contado"] == 109_000
    assert resultado["diferencia"] == -1_000

    guardado = storage.read_sheet(schema.CUADRE_CAJA)
    assert len(guardado) == 1
    assert int(guardado.iloc[0]["diferencia"]) == -1_000
    assert guardado.iloc[0]["nota"] == "sobra un billete"


def test_registrar_cuadre_caja_requiere_capacidad_cuadre_caja():
    storage = construir_storage()
    # vendedor SÍ tiene "cuadre_caja" (§10) — probamos que un rol sin
    # ninguna capacidad lo rechaza.
    with pytest.raises(PermisoDenegadoError):
        registrar_cuadre_caja(storage, "fantasma", HOY, "principal", 0, 0, "")


def test_vendedor_puede_registrar_cuadre_caja():
    storage = construir_storage()
    resultado = registrar_cuadre_caja(storage, VENDEDOR, HOY, "principal", 50_000, 50_000, "")
    assert resultado["diferencia"] == 0


def test_cuadre_caja_con_texto_que_empieza_por_signo_igual_no_se_pierde():
    storage = construir_storage()
    resultado = registrar_cuadre_caja(storage, ADMIN, HOY, "principal", 0, 0, "=1+1 no es formula")
    assert resultado["nota"] == "=1+1 no es formula"
    guardado = storage.read_sheet(schema.CUADRE_CAJA)
    assert guardado.iloc[0]["nota"] == "=1+1 no es formula"
