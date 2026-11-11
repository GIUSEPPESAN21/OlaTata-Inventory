"""Construcción y verificación de los libros de cierre mensual (§8).

Funciones de bajo nivel, SIN conocimiento de permisos ni de la base viva:
construyen el .xlsx de un cierre a partir de un snapshot en memoria,
calculan su huella (SHA-256) y mantienen la estructura de
`cierres/INDEX.json` (lista de cierres publicados, con su nombre de
archivo, el conteo de filas por hoja y el SHA-256 — usado por
`core.monthly_close` para verificar un cierre recién publicado sin confiar
ciegamente en que la subida tuvo éxito).

Este módulo NO habla con GitHub/Archive directamente: recibe y devuelve
`bytes` en memoria. Quien lo llama (`core.monthly_close`) es responsable
de pasarlos a `storage.archive_put_bytes` / leerlos de
`storage.archive_get_bytes`.
"""
from __future__ import annotations

import hashlib
import json
from io import BytesIO

import openpyxl
import pandas as pd

from core.timeutil import now_utc, to_iso_utc

__all__ = [
    "sha256_bytes",
    "construir_libro_cierre",
    "leer_libro_cierre",
    "leer_index",
    "serializar_index",
    "construir_entrada_index",
    "actualizar_index",
]


def sha256_bytes(contenido: bytes) -> str:
    """SHA-256 hexadecimal de un contenido binario (huella del cierre
    publicado, usada para verificar que lo descargado es lo que se subió)."""
    return hashlib.sha256(contenido).hexdigest()


def construir_libro_cierre(hojas: dict[str, pd.DataFrame]) -> bytes:
    """Serializa un snapshot de cierre (dict nombre_hoja -> DataFrame) a un
    .xlsx en memoria, con el mismo cuidado que `core.storage.Storage`
    aplica al libro vivo (R11): toda celda de texto se fuerza a
    `data_type="s"` (un valor como "=1+1" nunca se guarda como fórmula) y
    los valores NaN se guardan como celda vacía.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nombre, df in hojas.items():
        ws = wb.create_sheet(title=nombre[:31])
        ws.append(list(df.columns))
        for _, fila in df.iterrows():
            valores = [None if pd.isna(v) else v for v in fila]
            ws.append(valores)
        for fila_celdas in ws.iter_rows(min_row=2):
            for celda in fila_celdas:
                if isinstance(celda.value, str):
                    celda.data_type = "s"
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def leer_libro_cierre(contenido: bytes) -> dict[str, pd.DataFrame]:
    """Inverso de `construir_libro_cierre`: lee todas las hojas de un .xlsx
    en memoria. Usado por el paso de verificación del cierre (§8, paso 3):
    "vuelve a descargar el archivo recién publicado y recalcula conteos y
    totales"."""
    crudo = pd.read_excel(BytesIO(contenido), sheet_name=None, engine="openpyxl", dtype=object)
    return {nombre: df.reset_index(drop=True) for nombre, df in crudo.items()}


def leer_index(contenido: bytes | None) -> dict:
    """Parsea `cierres/INDEX.json`. Si todavía no existe (primer cierre de
    la vida del negocio) o está vacío, devuelve la estructura inicial."""
    if not contenido:
        return {"cierres": []}
    datos = json.loads(contenido.decode("utf-8"))
    datos.setdefault("cierres", [])
    return datos


def serializar_index(index: dict) -> bytes:
    """Serializa el índice a bytes UTF-8 legibles (JSON con sangría)."""
    return json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")


def construir_entrada_index(archivo: str, hojas: dict[str, pd.DataFrame], sha256: str) -> dict:
    """Entrada de `INDEX.json` para un cierre: nombre de archivo, conteo de
    filas por hoja y SHA-256 (§8, paso 2)."""
    return {
        "archivo": archivo,
        "filas_por_hoja": {nombre: int(len(df)) for nombre, df in hojas.items()},
        "sha256": sha256,
        "publicado_at": to_iso_utc(now_utc()),
    }


def actualizar_index(index: dict, entrada: dict) -> dict:
    """Agrega `entrada` a `index["cierres"]`, o la REEMPLAZA si ya existía
    una entrada con el mismo "archivo" (idempotente: reejecutar el paso 2
    tras una caída nunca duplica la fila del mismo mes en el índice,
    §8 "idempotente y a prueba de cortes")."""
    cierres = [c for c in index.get("cierres", []) if c.get("archivo") != entrada["archivo"]]
    cierres.append(entrada)
    cierres.sort(key=lambda c: c["archivo"])
    return {**index, "cierres": cierres}
