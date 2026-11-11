"""Fixtures compartidas. `FakeStorage` cumple el MISMO contrato público
que `core.storage.Storage` (ver docs/CONTRATOS.md) pero 100% en memoria,
sin red ni disco — así las pruebas de dominio (venta, inventario,
análisis, cierre) nunca dependen de GitHub ni del sistema de archivos.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass

import pandas as pd
import pytest

from core import auth, schema
from core.timeutil import now_utc, to_iso_utc


@dataclass
class SyncStatus:
    pendientes: int = 0
    en_conflicto: bool = False
    ultimo_error: str | None = None
    ultimo_sync_utc: str | None = None


class FakeStorage:
    """Doble en memoria de `core.storage.Storage`. Mismo contrato público:
    transaction(), read_sheet(), write_sheet(), get_config()/set_config(),
    next_counter(), sync_status(), archive_get_bytes()/archive_put_bytes().
    """

    def __init__(self, sheets: dict[str, pd.DataFrame] | None = None) -> None:
        self._lock = threading.RLock()
        self._sheets: dict[str, pd.DataFrame] = sheets or {
            name: pd.DataFrame(columns=schema.columnas(name)) for name in schema.SHEET_NAMES
        }
        self._in_transaction = False
        self._sync = SyncStatus()
        self.archive_repo = "fake/archive"
        self.archive_files: dict[str, bytes] = {}
        self.transacciones_confirmadas = 0

    # ---------------------------------------------------------- lectura
    def read_sheet(self, name: str) -> pd.DataFrame:
        if name not in schema.SHEET_COLUMNS:
            raise KeyError(f"Hoja desconocida: {name}")
        return self._sheets[name].copy()

    def get_config(self, clave: str, default: str | None = None) -> str | None:
        df = self.read_sheet(schema.CONFIG)
        fila = df[df["clave"] == clave]
        if fila.empty:
            return default
        valor = fila.iloc[0]["valor"]
        return default if pd.isna(valor) else str(valor)

    # ------------------------------------------------------- transaccion
    @contextmanager
    def transaction(self):
        with self._lock:
            respaldo = {k: v.copy() for k, v in self._sheets.items()}
            self._in_transaction = True
            try:
                yield self
            except Exception:
                self._sheets = respaldo
                raise
            else:
                self.transacciones_confirmadas += 1
            finally:
                self._in_transaction = False

    def write_sheet(self, name: str, df: pd.DataFrame) -> None:
        if not self._in_transaction:
            raise RuntimeError("write_sheet solo es válido dentro de transaction().")
        if name not in schema.SHEET_COLUMNS:
            raise KeyError(f"Hoja desconocida: {name}")
        columnas = schema.columnas(name)
        faltantes = set(columnas) - set(df.columns)
        if faltantes:
            raise ValueError(f"A la hoja '{name}' le faltan columnas: {sorted(faltantes)}")
        self._sheets[name] = df[columnas].reset_index(drop=True).copy()

    def set_config(self, clave: str, valor: str) -> None:
        if not self._in_transaction:
            raise RuntimeError("set_config solo es válido dentro de transaction().")
        df = self._sheets[schema.CONFIG]
        ahora = to_iso_utc(now_utc())
        coincide = df["clave"] == clave
        if coincide.any():
            df.loc[coincide, "valor"] = valor
            df.loc[coincide, "updated_at"] = ahora
        else:
            nueva = pd.DataFrame([{"clave": clave, "valor": valor, "created_at": ahora, "updated_at": ahora}])
            self._sheets[schema.CONFIG] = pd.concat([df, nueva], ignore_index=True)

    def next_counter(self, nombre: str, reset_key: str | None = None) -> int:
        if not self._in_transaction:
            raise RuntimeError("next_counter solo es válido dentro de transaction().")
        clave = f"contador::{nombre}::{reset_key or 'global'}"
        actual = int(self.get_config(clave, "0") or "0")
        siguiente = actual + 1
        self.set_config(clave, str(siguiente))
        return siguiente

    def sync_status(self) -> SyncStatus:
        return self._sync

    # ------------------------------------------------ cliente de Archive
    def archive_get_bytes(self, path: str) -> bytes | None:
        return self.archive_files.get(path)

    def archive_put_bytes(self, path: str, content: bytes, message: str) -> dict:
        self.archive_files[path] = content
        return {"content": {"sha": f"fake-sha-{len(content)}"}}


@pytest.fixture(autouse=True)
def _reset_auth_global_state():
    """Los intentos de login de `core.auth` viven en memoria de proceso;
    se limpian entre pruebas para que no se contaminen entre sí."""
    auth.reset_intentos_para_pruebas()
    yield
    auth.reset_intentos_para_pruebas()


@pytest.fixture
def storage() -> FakeStorage:
    """Storage en memoria, vacío, listo para usar en pruebas de dominio."""
    return FakeStorage()
