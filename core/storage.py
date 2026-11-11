"""Capa de datos: transacción atómica con lock + publicación síncrona a
GitHub con control de conflicto por SHA + respaldo local.

Adaptado del patrón de UNIMINUTO-Lab-Inventory core/storage.py (ver
docs/CONTRATOS.md para la investigación):
- Un `threading.RLock` serializa toda sección crítica de lectura-
  modificación-escritura (`transaction()`); así una venta concurrente por
  20 hilos nunca sobrevende la última unidad.
- La publicación a GitHub ocurre DESPUÉS de escribir local, nunca antes,
  y siempre comparando el SHA remoto conocido contra el SHA remoto real
  en este instante: si cambiaron, se rechaza (nunca se sobrescribe) y se
  marca `en_conflicto=True` en `sync_status()` — el admin resuelve desde
  Ajustes.
- Ante 409/422 de la API de GitHub se reintenta hasta `_PUT_RACE_RETRIES`
  veces (carrera transitoria, no conflicto real).
- Antes de aceptar un nuevo contenido local se guarda un respaldo `.bak`.
- Si GitHub no responde (red caída): la venta NO se pierde ni se
  duplica — ya quedó guardada atómicamente en el archivo local; solo se
  incrementa `sync_status().pendientes` para que la UI muestre el aviso.

CONTRATO CONGELADO — ver docs/CONTRATOS.md. Firmas públicas estables:
Storage(...), .transaction(), .read_sheet(), .write_sheet(),
.get_config()/.set_config(), .next_counter(), .sync_status(),
.archive_get_bytes()/.archive_put_bytes().
"""
from __future__ import annotations

import base64
import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import openpyxl
import pandas as pd
import requests

from core import schema
from core.timeutil import now_utc, to_iso_utc

GITHUB_API = "https://api.github.com"
_PUT_RACE_RETRIES = 2
_HTTP_TIMEOUT = 20


class ConflictoDeSincronizacionError(Exception):
    """El contenido remoto cambió desde el último SHA conocido; no se
    sobrescribe. Debe resolverse manualmente (Ajustes → estado de sync)."""


@dataclass
class SyncStatus:
    pendientes: int = 0
    en_conflicto: bool = False
    ultimo_error: str | None = None
    ultimo_sync_utc: str | None = None


class Storage:
    """Acceso al libro vivo (OLATATA_DB.xlsx). Ver docs/CONTRATOS.md."""

    def __init__(
        self,
        local_path: str | Path,
        github_repo: str | None = None,
        github_token: str | None = None,
        archive_repo: str | None = None,
        sync_enabled: bool = True,
    ) -> None:
        self.local_path = Path(local_path)
        self.github_repo = github_repo
        self.github_token = github_token
        self.archive_repo = archive_repo
        self.sync_enabled = bool(sync_enabled and github_repo and github_token)

        self._lock = threading.RLock()
        self._sheets: dict[str, pd.DataFrame] = {}
        self._loaded = False
        self._in_transaction = False
        self._known_remote_sha: str | None = None
        self._sync = SyncStatus()

    # ------------------------------------------------------------- carga
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.local_path.exists():
            self._sheets = self._read_workbook(self.local_path)
        else:
            self._sheets = {name: pd.DataFrame(columns=schema.columnas(name)) for name in schema.SHEET_NAMES}
        self._loaded = True

    @staticmethod
    def _read_workbook(path: Path) -> dict[str, pd.DataFrame]:
        crudo = pd.read_excel(path, sheet_name=None, engine="openpyxl", dtype=object)
        sheets: dict[str, pd.DataFrame] = {}
        for name in schema.SHEET_NAMES:
            columnas = schema.columnas(name)
            if name in crudo:
                df = crudo[name].copy()
                for col in columnas:
                    if col not in df.columns:
                        df[col] = pd.NA
                sheets[name] = df[columnas].reset_index(drop=True)
            else:
                sheets[name] = pd.DataFrame(columns=columnas)
        return sheets

    # ---------------------------------------------------------- lectura
    def read_sheet(self, name: str) -> pd.DataFrame:
        self._ensure_loaded()
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
    def transaction(self) -> Iterator["Storage"]:
        """Sección crítica atómica. Al salir SIN excepción, persiste a
        disco de forma atómica y publica de forma síncrona a GitHub. Si
        hay excepción, descarta todo cambio (no queda nada a medias, R6)."""
        with self._lock:
            self._ensure_loaded()
            respaldo = {k: v.copy() for k, v in self._sheets.items()}
            self._in_transaction = True
            try:
                yield self
            except Exception:
                self._sheets = respaldo
                raise
            else:
                self._persist_and_publish()
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
            nueva = pd.DataFrame(
                [{"clave": clave, "valor": valor, "created_at": ahora, "updated_at": ahora}]
            )
            self._sheets[schema.CONFIG] = pd.concat([df, nueva], ignore_index=True)

    def next_counter(self, nombre: str, reset_key: str | None = None) -> int:
        """Contador atómico (solo dentro de `transaction()`). Base para IDs
        únicos (p.ej. "OT-000001") o numeración que reinicia por mes
        ("2026-11-0001", pasando reset_key="2026-11")."""
        if not self._in_transaction:
            raise RuntimeError("next_counter solo es válido dentro de transaction().")
        clave = f"contador::{nombre}::{reset_key or 'global'}"
        actual = int(self.get_config(clave, "0") or "0")
        siguiente = actual + 1
        self.set_config(clave, str(siguiente))
        return siguiente

    # ---------------------------------------------------- persistencia
    def _persist_and_publish(self) -> None:
        self._write_local_atomic()
        if self.sync_enabled:
            self._publish_to_github()
        else:
            self._sync.pendientes += 1

    def _write_local_atomic(self) -> None:
        tmp_path = self.local_path.with_suffix(".tmp")
        self._write_workbook(tmp_path, self._sheets)
        if self.local_path.exists():
            shutil.copyfile(self.local_path, self.local_path.with_suffix(".bak"))
        os.replace(tmp_path, self.local_path)

    @staticmethod
    def _write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name in schema.SHEET_NAMES:
            df = sheets[name]
            ws = wb.create_sheet(title=name[:31])
            ws.append(list(df.columns))
            for _, fila in df.iterrows():
                valores = [None if pd.isna(v) else v for v in fila]
                ws.append(valores)
            # R11: ninguna celda de texto se guarda jamás como fórmula,
            # sin importar con qué carácter empiece (p.ej. "=1+1").
            for fila_celdas in ws.iter_rows(min_row=2):
                for celda in fila_celdas:
                    if isinstance(celda.value, str):
                        celda.data_type = "s"
        wb.save(path)

    # -------------------------------------------------------- sync GitHub
    def _publish_to_github(self) -> None:
        contenido = self.local_path.read_bytes()
        try:
            resultado = self._github_put(self.github_repo, self._remote_path(), contenido)
        except ConflictoDeSincronizacionError as exc:
            self._sync.en_conflicto = True
            self._sync.ultimo_error = str(exc)
            self._sync.pendientes += 1
            return
        except Exception as exc:  # red caída / timeout: la venta ya está a salvo localmente
            self._sync.ultimo_error = str(exc)
            self._sync.pendientes += 1
            return
        self._known_remote_sha = resultado.get("content", {}).get("sha")
        self._sync.pendientes = 0
        self._sync.en_conflicto = False
        self._sync.ultimo_error = None
        self._sync.ultimo_sync_utc = to_iso_utc(now_utc())

    def _remote_path(self) -> str:
        return self.local_path.name

    def _github_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github+json"}

    def _github_get_sha(self, repo: str, path: str) -> str | None:
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        resp = requests.get(url, headers=self._github_headers(), timeout=_HTTP_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("sha")

    def _github_put(self, repo: str, path: str, contenido: bytes, intento: int = 0) -> dict:
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        sha_actual = self._github_get_sha(repo, path)
        if self._known_remote_sha is not None and sha_actual != self._known_remote_sha:
            raise ConflictoDeSincronizacionError(
                f"'{path}' cambió en GitHub (sha esperado={self._known_remote_sha}, actual={sha_actual})."
            )
        payload = {"message": f"Actualiza {path} ({to_iso_utc(now_utc())})", "content": base64.b64encode(contenido).decode("ascii")}
        if sha_actual is not None:
            payload["sha"] = sha_actual
        resp = requests.put(url, headers=self._github_headers(), json=payload, timeout=_HTTP_TIMEOUT * 2)
        if resp.status_code in (409, 422):
            if intento < _PUT_RACE_RETRIES:
                return self._github_put(repo, path, contenido, intento + 1)
            raise ConflictoDeSincronizacionError(f"GitHub rechazó la publicación de '{path}' tras {intento + 1} intentos.")
        resp.raise_for_status()
        return resp.json()

    def sync_status(self) -> SyncStatus:
        return self._sync

    # ------------------------------------------------ cliente de Archive
    def archive_get_bytes(self, path: str) -> bytes | None:
        if not self.archive_repo:
            return None
        sha = self._github_get_sha(self.archive_repo, path)
        if sha is None:
            return None
        url = f"{GITHUB_API}/repos/{self.archive_repo}/contents/{path}"
        resp = requests.get(url, headers=self._github_headers(), timeout=_HTTP_TIMEOUT * 2)
        resp.raise_for_status()
        return base64.b64decode(resp.json()["content"])

    def archive_put_bytes(self, path: str, content: bytes, message: str) -> dict:
        if not self.archive_repo:
            raise RuntimeError("No hay archive_repo configurado.")
        sha_actual = self._github_get_sha(self.archive_repo, path)
        url = f"{GITHUB_API}/repos/{self.archive_repo}/contents/{path}"
        payload = {"message": message, "content": base64.b64encode(content).decode("ascii")}
        if sha_actual is not None:
            payload["sha"] = sha_actual
        resp = requests.put(url, headers=self._github_headers(), json=payload, timeout=_HTTP_TIMEOUT * 2)
        resp.raise_for_status()
        return resp.json()
