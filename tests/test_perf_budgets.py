"""Presupuestos de rendimiento del §11 (propiedad de A6).

Como `core.sales` y `core.analytics` (propiedad de A1-A2) no existen
todavía en esta rama, estas pruebas miden directamente contra
`core.storage.Storage` (API ya congelada) como aproximación:

- "abrir Análisis <2s con 3000 ventas en el mes": `storage.read_sheet()`
  no toca disco después de la primera carga (los datos quedan en memoria
  dentro de `Storage`), así que esto SÍ se puede medir de verdad hoy.
- "confirmar una venta <3s con GitHub disponible (<500ms en local)": se
  mide con una `transaction()` real (disco, sin red) sobre un libro ya
  poblado a la escala del propio ejemplo del encargo (~3000 ventas). A6
  encontró aquí un hallazgo real: con el `_write_workbook` original
  (openpyxl normal) esto medía ~5-6s por venta, muy por encima del
  presupuesto. El agente principal lo corrigió reemplazando la escritura
  por `core/fastxlsx.py` (OOXML hecho a mano, sin el overhead por-celda
  de openpyxl) — con eso esta prueba YA PASA de verdad (~0.3s a esta
  escala), así que el `xfail` que A6 dejó aquí se quitó.
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager

import pandas as pd

from core import schema
from core.storage import Storage

N_VENTAS_ESCALA = 3000
N_ITEMS_ESCALA = 6000


@contextmanager
def _medir_tiempo_real():
    """Mide tiempo real de producción, sin el overhead de instrumentación
    de `coverage.py` (vía `sys.settrace`), que por sí solo puede casi
    duplicar la duración de un bucle ajustado como el de `fastxlsx` y
    volver la prueba intermitente cuando el CI corre con `--cov=core`
    (medido: 0.32s sin cobertura vs 0.86s con cobertura, mismo código)."""
    trace_anterior = sys.gettrace()
    sys.settrace(None)
    try:
        yield
    finally:
        sys.settrace(trace_anterior)


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


def test_confirmar_venta_bajo_500ms_en_local_con_3000_ventas(tmp_path):
    storage = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False)
    _poblar_a_escala(storage)

    with _medir_tiempo_real():
        t0 = time.perf_counter()
        with storage.transaction() as tx:
            df = tx.read_sheet(schema.VENTAS)
            nueva = pd.DataFrame([{c: "y" for c in schema.columnas(schema.VENTAS)}])
            tx.write_sheet(schema.VENTAS, pd.concat([df, nueva], ignore_index=True))
        duracion = time.perf_counter() - t0

    assert duracion < 0.5, f"Confirmar una venta tardó {duracion:.3f}s a escala de 3000 ventas (presupuesto: <500ms local)."


def test_confirmar_venta_bajo_3s_con_github_disponible_con_3000_ventas(tmp_path, monkeypatch):
    storage = Storage(
        local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="demo/repo", github_token="t", sync_enabled=True
    )

    class _RespuestaFalsa:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

        def raise_for_status(self):
            return None

    # Base nueva en la nube (404 al abrirla): la población inicial publica
    # y deja `_known_remote_sha="fake-sha"`. Desde ahí, GitHub "disponible"
    # devuelve ese mismo sha y cada venta publica sin conflicto.
    monkeypatch.setattr("core.storage.requests.get", lambda *a, **k: _RespuestaFalsa({}, 404))
    monkeypatch.setattr("core.storage.requests.put", lambda *a, **k: _RespuestaFalsa({"content": {"sha": "fake-sha"}}))
    _poblar_a_escala(storage)

    monkeypatch.setattr("core.storage.requests.get", lambda *a, **k: _RespuestaFalsa({"sha": "fake-sha"}))
    monkeypatch.setattr("core.storage.requests.put", lambda *a, **k: _RespuestaFalsa({"content": {"sha": "fake-sha"}}))

    with _medir_tiempo_real():
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
