"""Cuadre de caja diario (§7 "HOY": Cuadre de caja).

`registrar_cuadre_caja` calcula el efectivo ESPERADO a partir de
`pagos` (método "efectivo") y `devoluciones` (reembolso en "efectivo")
del día local, lo compara contra el efectivo CONTADO que reporta el
usuario, y guarda la diferencia — nunca se "ajusta" el contado, la
diferencia queda registrada tal cual para que el admin la revise.

CONTRATO CONGELADO (ver docs/CONTRATOS.md): este módulo NUNCA modifica
`core/schema.py`, `core/money.py`, `core/timeutil.py`, `core/storage.py`
ni `core/permissions.py` — solo los importa.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from core import schema
from core.analytics import dia_bounds_utc
from core.excel_safe import excel_safe
from core.money import parse_pesos
from core.permissions import requerir
from core.timeutil import now_utc, to_iso_utc

__all__ = ["registrar_cuadre_caja", "efectivo_esperado_del_dia"]


def _entero(serie: pd.Series) -> pd.Series:
    if serie.empty:
        return serie.astype("int64")
    return pd.to_numeric(serie, errors="coerce").fillna(0).astype("int64")


def efectivo_esperado_del_dia(storage: Any, fecha_local: date, base_inicial: int) -> int:
    """`base_inicial` + pagos en efectivo del día − reembolsos en
    efectivo del día (ambos filtrados por SU PROPIA `fecha_hora_utc`,
    nunca por la fecha de la venta original — mismo criterio que
    `core.analytics` usa para "flujo de caja")."""
    inicio_utc, fin_utc = dia_bounds_utc(fecha_local)

    pagos = storage.read_sheet(schema.PAGOS)
    if not pagos.empty:
        ts = pd.to_datetime(pagos["fecha_hora_utc"], utc=True, errors="coerce")
        en_rango = (ts >= pd.Timestamp(inicio_utc)) & (ts < pd.Timestamp(fin_utc))
        efectivo_pagos = pagos[en_rango & (pagos["metodo"] == "efectivo")]
        total_pagos = int(_entero(efectivo_pagos["monto"]).sum()) if not efectivo_pagos.empty else 0
    else:
        total_pagos = 0

    devoluciones = storage.read_sheet(schema.DEVOLUCIONES)
    if not devoluciones.empty:
        ts = pd.to_datetime(devoluciones["fecha_hora_utc"], utc=True, errors="coerce")
        en_rango = (ts >= pd.Timestamp(inicio_utc)) & (ts < pd.Timestamp(fin_utc))
        reembolsos_efectivo = devoluciones[en_rango & (devoluciones["reembolso_metodo"] == "efectivo")]
        total_reembolsos = int(_entero(reembolsos_efectivo["reembolso_monto"]).sum()) if not reembolsos_efectivo.empty else 0
    else:
        total_reembolsos = 0

    return int(base_inicial) + total_pagos - total_reembolsos


def registrar_cuadre_caja(
    storage: Any,
    rol: str,
    fecha_local: date,
    sede_id: str,
    base_inicial: object,
    efectivo_contado: object,
    nota: str = "",
    usuario_id: str | None = None,
) -> dict[str, Any]:
    """Registra el cuadre de caja del día. Requiere capacidad "cuadre_caja".

    Guarda una fila nueva en `cuadre_caja` (dentro de una transacción
    atómica, R6) con `efectivo_esperado`, `efectivo_contado` y la
    `diferencia` (contado − esperado). No lanza si hay diferencia: el
    cuadre registra la realidad, la revisión es un proceso humano.
    """
    requerir(rol, "cuadre_caja")

    base_inicial_int = parse_pesos(base_inicial)
    efectivo_contado_int = parse_pesos(efectivo_contado)
    nota_segura = excel_safe(nota, field_name="nota")

    esperado = efectivo_esperado_del_dia(storage, fecha_local, base_inicial_int)
    diferencia = efectivo_contado_int - esperado

    with storage.transaction() as tx:
        df = tx.read_sheet(schema.CUADRE_CAJA)
        ahora = to_iso_utc(now_utc())
        nuevo_id = f"cuadre-{tx.next_counter('cuadre_caja')}"
        fila = {
            "id": nuevo_id,
            "fecha_local": fecha_local.isoformat(),
            "sede_id": sede_id,
            "base_inicial": base_inicial_int,
            "efectivo_esperado": esperado,
            "efectivo_contado": efectivo_contado_int,
            "diferencia": diferencia,
            "nota": nota_segura,
            "usuario_id": usuario_id,
            "created_at": ahora,
            "updated_at": ahora,
        }
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        tx.write_sheet(schema.CUADRE_CAJA, df)

    return {
        "id": nuevo_id,
        "fecha_local": fecha_local.isoformat(),
        "sede_id": sede_id,
        "base_inicial": base_inicial_int,
        "efectivo_esperado": esperado,
        "efectivo_contado": efectivo_contado_int,
        "diferencia": diferencia,
        "nota": nota_segura,
    }
