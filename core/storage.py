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
import json
import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

from core import fastxlsx, schema
from core.timeutil import now_utc, to_iso_utc

GITHUB_API = "https://api.github.com"
_PUT_RACE_RETRIES = 2
_HTTP_TIMEOUT = 20
# Archivo "sidecar" junto al libro local: recuerda contra qué versión
# remota (sha) se sincronizó por última vez la copia local y si quedaron
# cambios locales sin publicar. Solo se usa con sync activo.
_SIDECAR_SUFFIX = ".sync.json"


class BaseDeDatosNoDisponibleError(Exception):
    """La base en la nube no se pudo leer y no hay copia local para
    trabajar sin conexión. Nunca se arranca con un libro vacío en ese caso:
    la primera transacción sobrescribiría la base real en GitHub."""


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
        # Versión remota (sha) contra la que se cargó la base al arrancar.
        # Informativo para Ajustes; la protección real la da
        # `_known_remote_sha` en `_github_put`.
        self.sha_remoto_cargado: str | None = None

    # ------------------------------------------------------------- carga
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.sync_enabled:
            # La nube (OlaTata-Database) es la fuente de verdad. En
            # Streamlit Cloud el disco es efímero: sin este paso, cada
            # reinicio del servidor arrancaba con un libro VACÍO y la
            # primera transacción sobrescribía la base real en GitHub
            # (hallazgo crítico: así se perdió la config del negocio).
            self._cargar_desde_nube()
        if self.local_path.exists():
            self._sheets = self._read_workbook(self.local_path)
        else:
            self._sheets = {name: pd.DataFrame(columns=schema.columnas(name)) for name in schema.SHEET_NAMES}
        self._loaded = True

    def _cargar_desde_nube(self) -> None:
        """Trae `OLATATA_DB.xlsx` desde GitHub ANTES de leer el disco.

        Reglas (la nube manda, pero nunca se pierde un cambio local):
        - Remoto existe y la copia local no tiene cambios pendientes ->
          se usa el remoto (si la copia local era distinta, se respalda
          como `<nombre>.local-<fecha>.xlsx` antes de reemplazarla).
        - La copia local tiene cambios sin publicar hechos sobre ESA MISMA
          versión remota (sha del sidecar == sha remoto) -> se conserva la
          local y queda pendiente de publicar (avance rápido, sin conflicto).
        - Remoto no existe (404) -> base nueva: se usa la local si existe.
        - Sin red y hay copia local -> se trabaja sin conexión; la próxima
          publicación compara contra el sha del sidecar (nunca a ciegas).
        - Sin red y sin copia local -> `BaseDeDatosNoDisponibleError`.
        """
        meta = self._leer_sidecar()
        try:
            remoto = self._github_descargar(self.github_repo, self._remote_path())
        except Exception as exc:
            if self.local_path.exists():
                self._known_remote_sha = meta.get("sha")
                self._sync.ultimo_error = f"Sin conexión con la nube al abrir la base: {exc}"
                if meta.get("pendiente"):
                    self._sync.pendientes = max(self._sync.pendientes, 1)
                return
            raise BaseDeDatosNoDisponibleError(
                "No se pudo descargar la base de datos desde GitHub y no hay copia local."
            ) from exc

        if remoto is None:  # todavía no existe en la nube: base nueva
            self._known_remote_sha = None
            if self.local_path.exists():
                self._sync.pendientes = max(self._sync.pendientes, 1)
            return

        contenido, sha = remoto
        self.sha_remoto_cargado = sha
        if self.local_path.exists() and meta.get("pendiente") and meta.get("sha") == sha:
            self._known_remote_sha = sha
            self._sync.pendientes = max(self._sync.pendientes, 1)
            return
        if self.local_path.exists() and self.local_path.read_bytes() != contenido:
            sello = now_utc().strftime("%Y%m%dT%H%M%SZ")
            respaldo = self.local_path.with_name(f"{self.local_path.stem}.local-{sello}{self.local_path.suffix}")
            shutil.copyfile(self.local_path, respaldo)
        self._escribir_bytes_atomico(self.local_path, contenido)
        self._known_remote_sha = sha
        self._escribir_sidecar(sha, pendiente=False)
        self._sync.ultimo_sync_utc = to_iso_utc(now_utc())

    @staticmethod
    def _escribir_bytes_atomico(path: Path, contenido: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".descarga.tmp")
        tmp.write_bytes(contenido)
        os.replace(tmp, path)

    def _sidecar_path(self) -> Path:
        return self.local_path.with_name(self.local_path.name + _SIDECAR_SUFFIX)

    def _leer_sidecar(self) -> dict:
        try:
            datos = json.loads(self._sidecar_path().read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def _escribir_sidecar(self, sha: str | None, *, pendiente: bool) -> None:
        try:
            self._sidecar_path().write_text(
                json.dumps({"sha": sha, "pendiente": pendiente, "actualizado_utc": to_iso_utc(now_utc())}),
                encoding="utf-8",
            )
        except OSError:
            pass  # el sidecar es una ayuda, nunca debe tumbar una venta

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
        hay excepción, descarta todo cambio (no queda nada a medias, R6).

        `_persist_and_publish()` se llama DENTRO del `try` (no en un
        `else` después de él, como antes): si la escritura local falla
        a mitad de camino (disco lleno, permiso denegado, un bug en
        `fastxlsx`), esa excepción debe revertir también la memoria —
        si no, una fila nunca escrita a disco queda "fantasma" en
        `self._sheets` y una transacción futura, no relacionada, la
        persiste y publica igual (hallazgo CRÍTICO de V2). La
        publicación a GitHub en sí (`_publish_to_github`) nunca
        propaga excepción — ver su propio manejo de errores — así que
        esto no cambia el comportamiento "offline-safe" ya documentado.
        """
        with self._lock:
            self._ensure_loaded()
            respaldo = {k: v.copy() for k, v in self._sheets.items()}
            self._in_transaction = True
            try:
                yield self
                self._persist_and_publish()
            except Exception:
                self._sheets = respaldo
                raise
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
            self._escribir_sidecar(self._known_remote_sha, pendiente=True)
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
        """Delega en `core.fastxlsx` (OOXML hecho a mano, sin el overhead
        por-celda de openpyxl). Hallazgo de A6: con openpyxl normal, una
        transacción incremental con un mes de alto volumen (1500 ventas /
        3750 items) tardaba ~2-3.5s, muy por encima del presupuesto de
        500ms (§11); con `fastxlsx` baja a milisegundos (ver benchmark en
        docs/CONTRATOS.md). R11 se garantiza en `fastxlsx` mismo: todo
        texto se escribe como `t="inlineStr"`, que nunca es fórmula.
        """
        fastxlsx.write_workbook(path, sheets, schema.SHEET_NAMES)

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
        self._escribir_sidecar(self._known_remote_sha, pendiente=False)
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
        if sha_actual != self._known_remote_sha:
            # Incluye el caso `_known_remote_sha is None` con un remoto que
            # SÍ existe: nunca se sobrescribe una base que esta instancia no
            # descargó primero (antes eso borraba datos reales en la nube).
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

    def _github_descargar(self, repo: str, path: str) -> tuple[bytes, str] | None:
        """Descarga un archivo del repo: `(contenido, sha)` o `None` si no
        existe. La API de contenidos solo incluye `content` en base64 para
        archivos de hasta 1 MB; por encima de eso (un mes de alto volumen)
        se pide el contenido crudo con `Accept: application/vnd.github.raw`."""
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        resp = requests.get(url, headers=self._github_headers(), timeout=_HTTP_TIMEOUT * 2)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        datos = resp.json()
        sha = datos.get("sha")
        if datos.get("encoding") == "base64" and datos.get("content"):
            return base64.b64decode(datos["content"]), sha
        headers = dict(self._github_headers(), Accept="application/vnd.github.raw")
        crudo = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT * 3)
        crudo.raise_for_status()
        return crudo.content, sha

    def sync_status(self) -> SyncStatus:
        return self._sync

    # --------------------------------------------- operaciones de sincronía
    def sincronizar_ahora(self) -> SyncStatus:
        """Reintenta publicar la copia local si quedó pendiente (p.ej. tras
        una caída de red). No hace nada si hay un conflicto sin resolver."""
        with self._lock:
            self._ensure_loaded()
            if self.sync_enabled and not self._sync.en_conflicto and self.local_path.exists():
                self._publish_to_github()
            return self._sync

    def resolver_conflicto_usar_nube(self) -> SyncStatus:
        """Descarta la copia local y recarga la versión de GitHub. La copia
        local NO se borra: queda como `<nombre>.conflicto-<fecha>.xlsx`."""
        with self._lock:
            if self.local_path.exists():
                sello = now_utc().strftime("%Y%m%dT%H%M%SZ")
                respaldo = self.local_path.with_name(f"{self.local_path.stem}.conflicto-{sello}{self.local_path.suffix}")
                shutil.copyfile(self.local_path, respaldo)
            self._escribir_sidecar(None, pendiente=False)
            self._sync = SyncStatus()
            self._loaded = False
            self._sheets = {}
            self._ensure_loaded()
            return self._sync

    def resolver_conflicto_conservar_local(self) -> SyncStatus:
        """Publica la copia local encima de la versión actual de GitHub. La
        versión remota no se pierde: sigue en el historial de commits del
        repo de datos (ver DEPLOY.md, "Restaurar una versión anterior")."""
        with self._lock:
            self._ensure_loaded()
            if not self.sync_enabled:
                return self._sync
            self._known_remote_sha = self._github_get_sha(self.github_repo, self._remote_path())
            self._sync.en_conflicto = False
            if not self.local_path.exists():
                self._write_local_atomic()
            self._publish_to_github()
            return self._sync

    # ------------------------------------------------ cliente de Archive
    def archive_get_bytes(self, path: str) -> bytes | None:
        if not self.archive_repo:
            return None
        resultado = self._github_descargar(self.archive_repo, path)
        return None if resultado is None else resultado[0]

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
