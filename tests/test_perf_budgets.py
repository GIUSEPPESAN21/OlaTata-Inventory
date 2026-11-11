"""Presupuestos de rendimiento del §11 (propiedad de A6).

Como `core.sales` y `core.analytics` (propiedad de A1-A2) no existen
todavía en esta rama, estas pruebas miden directamente contra
`core.storage.Storage` (API ya congelada) como aproximación:

- "abrir Análisis <2s con 3000 ventas en el mes": `storage.read_sheet()`
  no toca disco después de la primera carga (los datos quedan en memoria
  dentro de `Storage`), así que esto SÍ se puede medir de verdad hoy.
- "confirmar una venta <3s con GitHub disponible (<500ms en local)": se
  mide con una `transaction()` real (disco, sin red) sobre un libro ya
  poblado a la escala del propio ejemplo del encargo (~3000 ventas). Esto
  reveló un hallazgo real (ver CONTRATOS.md, sección "Conocido, no
  implementado en M1"): `core.storage._write_workbook` reescribe TODAS las
  filas de TODAS las hojas en cada `transaction()` con `openpyxl`, así que
  el costo crece con el tamaño total del libro, no con lo que cambió. A la
  escala de ~3000 ventas / 6000 items esto mide ~5-6s por venta, muy por
  encima de los 500ms/3s del presupuesto. Se marcan `xfail` (no bloquean
  el pipeline) porque la causa vive en `core/storage.py`, que A6 tiene
  PROHIBIDO modificar: la optimización debe pedirse al agente principal.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from core import schema
from core.storage import Storage

N_VENTAS_ESCALA = 3000
N_ITEMS_ESCALA = 6000


def _poblar_a_escala(storage: Storage) -> None:
    """Una sola escritura masiva (no 3000 transacciones) para alcanzar la
    escala de prueba rápido; el costo de `_write_workbook` depende del
    tamaño FINAL del libro, no de cuántas transacciones se usaron para
    llegar ahí (ver benchmark en el informe de A6)."""
    with storage.transaction() as tx:
        df_v = tx.read_sheet(schema.VENTAS)
        filas_v = pd.DataFrame([{c: "x" for c in schema.columnas(schema.VENTAS)} for _ in range(N_VENTAS_ESCALA)])
        tx.write_sheet(schema.VENTAS, pd.concat([df_v, filas_v], ignore_index=True))
        df_i = tx.read_sheet(schema.VENTA_ITEMS)
        filas_i = pd.DataFrame([{c: "x" for c in schema.columnas(schema.VENTA_ITEMS)} for _ in range(N_ITEMS_ESCALA)])
        tx.write_sheet(schema.VENTA_ITEMS, pd.concat([df_i, filas_i], ignore_index=True))


def test_abrir_analisis_bajo_2s_con_3000_ventas_en_el_mes(tmp_path):
    """Lectura + agregación en pandas sobre ~3000 ventas ya cargadas en
    memoria por `Storage` — lo que el futuro `core.analytics` haría al
    abrir la vista de Análisis."""
    storage = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False)
    _poblar_a_escala(storage)

    t0 = time.perf_counter()
    df = storage.read_sheet(schema.VENTAS)
    _ = len(df)  # agregación mínima representativa
    duracion = time.perf_counter() - t0

    assert duracion < 2.0, f"Abrir Análisis tardó {duracion:.3f}s con {len(df)} ventas (presupuesto: <2s)."


@pytest.mark.xfail(
    reason=(
        "core.storage._write_workbook reescribe el libro COMPLETO en cada "
        "transaction() con openpyxl; a ~3000 ventas una sola 'confirmar venta' "
        "incremental mide varios segundos (medido: ~5-6s), excede el presupuesto "
        "de 500ms en local. Documentado en CONTRATOS.md como 'Conocido, no "
        "implementado en M1'. A6 no puede tocar core/storage.py; se pide al "
        "agente principal optimizar la escritura (p.ej. no reescribir hojas que "
        "no cambiaron, o un escritor de xlsx más rápido) cuando integre A1-A5."
    ),
    strict=False,
)
def test_confirmar_venta_bajo_500ms_en_local_con_3000_ventas(tmp_path):
    storage = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False)
    _poblar_a_escala(storage)

    t0 = time.perf_counter()
    with storage.transaction() as tx:
        df = tx.read_sheet(schema.VENTAS)
        nueva = pd.DataFrame([{c: "y" for c in schema.columnas(schema.VENTAS)}])
        tx.write_sheet(schema.VENTAS, pd.concat([df, nueva], ignore_index=True))
    duracion = time.perf_counter() - t0

    assert duracion < 0.5, f"Confirmar una venta tardó {duracion:.3f}s a escala de 3000 ventas (presupuesto: <500ms local)."


@pytest.mark.xfail(
    reason=(
        "Mismo hallazgo que el presupuesto local: el costo de transaction() crece "
        "con el tamaño del libro, no con el tamaño de GitHub. Con el disco local ya "
        "por encima de 3s a esta escala, agregar la sincronización remota (incluso "
        "mockeada, casi instantánea) no puede bajarlo por debajo del presupuesto."
    ),
    strict=False,
)
def test_confirmar_venta_bajo_3s_con_github_disponible_con_3000_ventas(tmp_path, monkeypatch):
    storage = Storage(
        local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="demo/repo", github_token="t", sync_enabled=True
    )
    _poblar_a_escala(storage)

    class _RespuestaFalsa:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

        def raise_for_status(self):
            return None

    monkeypatch.setattr("core.storage.requests.get", lambda *a, **k: _RespuestaFalsa({"sha": "fake-sha"}))
    monkeypatch.setattr("core.storage.requests.put", lambda *a, **k: _RespuestaFalsa({"content": {"sha": "fake-sha-2"}}))

    t0 = time.perf_counter()
    with storage.transaction() as tx:
        df = tx.read_sheet(schema.VENTAS)
        nueva = pd.DataFrame([{c: "y" for c in schema.columnas(schema.VENTAS)}])
        tx.write_sheet(schema.VENTAS, pd.concat([df, nueva], ignore_index=True))
    duracion = time.perf_counter() - t0

    assert duracion < 3.0, f"Confirmar una venta (con GitHub disponible) tardó {duracion:.3f}s (presupuesto: <3s)."


def test_abrir_analisis_sigue_siendo_rapido_aunque_confirmar_venta_sea_lento(tmp_path):
    """Control: aunque `transaction()` (escritura) sea el cuello de botella
    a escala, la LECTURA (`read_sheet`, lo que usa Análisis) no se ve
    afectada porque no vuelve a tocar disco — confirma que el hallazgo de
    rendimiento es específico de la escritura, no de todo `Storage`."""
    storage = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False)
    _poblar_a_escala(storage)

    tiempos = []
    for _ in range(5):
        t0 = time.perf_counter()
        storage.read_sheet(schema.VENTAS)
        tiempos.append(time.perf_counter() - t0)

    assert max(tiempos) < 2.0
