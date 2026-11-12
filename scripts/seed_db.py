"""Siembra inicial del libro VIVO de producción (OLATATA_DB.xlsx) y su
publicación en OlaTata-Database. Propiedad del agente coordinador (§B).

`sembrar_config(tx)` es la única pieza de lógica de negocio y se prueba
en `tests/test_seed_db.py` con `FakeStorage` (sin red). El resto de este
archivo es orquestación de CLI: construye un `core.storage.Storage` real,
corre `sembrar_config` dentro de una `transaction()` (lo que escribe
local y publica a GitHub en un solo paso atómico, por contrato de
`Storage._persist_and_publish`), y luego relee el contenido YA publicado
en GitHub para confirmar que todas las hojas y la config llegaron bien.

Claves de configuración reales, consumidas hoy por la app (ver
`views/ajustes.py`, `core/sales.py`, `views/vender.py` — es el contrato
vivo, no los nombres "ideales" de la especificación original):

    negocio_nombre, negocio_whatsapp, telefono_whatsapp,
    negocio_mensaje_recibo, negocio_categorias (separadas por "|"),
    negocio_metodos_pago_activos (separadas por "|"), sesion_minutos,
    permitir_vender_sin_stock ("true"/"false").

Además se siembran unas pocas claves informativas que ningún módulo lee
todavía (instagram, ciudades, zona_horaria, moneda) por si un módulo de
tema/encabezado las necesita más adelante — no rompen nada porque CONFIG
es clave/valor libre.

Uso:
    GITHUB_TOKEN=... python scripts/seed_db.py
    python scripts/seed_db.py --verify-only   # solo relee lo publicado
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.excel_safe import excel_safe  # noqa: E402

GITHUB_REPO_DEFAULT = "GIUSEPPESAN21/OlaTata-Database"
GITHUB_REPO_ARCHIVE_DEFAULT = "GIUSEPPESAN21/OlaTata-Archive"
LOCAL_DB_NAME = "OLATATA_DB.xlsx"

CATEGORIAS_INICIALES = [
    "Bolsos",
    "Carteras",
    "Mochilas",
    "Billeteras",
    "Cosmetiqueros",
    "Canguros",
    "Correas y cinturones",
    "Bisutería",
    "Accesorios para el cabello",
    "Gafas",
    "Otros",
]

MENSAJE_RECIBO = (
    "¡Gracias por tu compra en Ola Tata! Síguenos en Instagram @olatata_1. "
    "Cambios con este recibo."
)

_SEP = "|"

# Única fuente de verdad para lo sembrado: `sembrar_config` la escribe,
# `_leer_publicado_desde_github` la usa para verificar byte a byte lo que
# quedó publicado, sin duplicar la lista de claves en dos sitios.
VALORES_CONFIG: dict[str, str] = {
    "negocio_nombre": "Ola Tata · Bolsos & Accesorios",
    "negocio_whatsapp": "573173003526",
    "telefono_whatsapp": "573173003526",
    "negocio_mensaje_recibo": MENSAJE_RECIBO,
    "negocio_categorias": _SEP.join(CATEGORIAS_INICIALES),
    "negocio_metodos_pago_activos": _SEP.join(sorted(schema.METODOS_PAGO)),
    "sesion_minutos": "480",
    "permitir_vender_sin_stock": "false",
    "instagram": "@olatata_1",
    "ciudades": "Buga, Tuluá",
    "zona_horaria": "America/Bogota",
    "moneda": "COP",
}


def sembrar_config(tx) -> dict[str, str]:
    """Escribe toda la config inicial dentro de una transacción ya abierta
    (`tx` es un `Storage`/`FakeStorage` en modo `transaction()`). Devuelve
    `VALORES_CONFIG`, para que la CLI y las pruebas puedan verificarlo sin
    tener que releer la hoja."""
    for clave, valor in VALORES_CONFIG.items():
        tx.set_config(clave, excel_safe(valor, max_length=4000, field_name=clave))
    return VALORES_CONFIG


def _construir_storage_real(local_path: Path):
    from core.storage import Storage

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO", GITHUB_REPO_DEFAULT)
    repo_archive = os.environ.get("GITHUB_REPO_ARCHIVE", GITHUB_REPO_ARCHIVE_DEFAULT)
    if not token:
        raise SystemExit(
            "Falta GITHUB_TOKEN en el entorno. Exporta un token con permiso "
            "'repo' sobre " + repo + " antes de correr este script."
        )
    return Storage(
        local_path=local_path,
        github_repo=repo,
        github_token=token,
        archive_repo=repo_archive,
        sync_enabled=True,
    )


def _leer_publicado_desde_github(repo: str, token: str) -> dict:
    """Descarga OLATATA_DB.xlsx YA PUBLICADO en GitHub (no el archivo
    local) y lo valida: las 13 hojas, columnas en el orden de
    `core/schema.py`, y que la config sembrada esté completa. Es la
    verificación de B2: "lee el libro de vuelta desde GitHub"."""
    import base64
    import io

    import pandas as pd
    import requests

    url = f"https://api.github.com/repos/{repo}/contents/{LOCAL_DB_NAME}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    contenido = base64.b64decode(resp.json()["content"])

    crudo = pd.read_excel(io.BytesIO(contenido), sheet_name=None, engine="openpyxl", dtype=object)

    reporte: dict = {"sha": resp.json().get("sha"), "hojas": {}, "problemas": []}
    for nombre in schema.SHEET_NAMES:
        if nombre not in crudo:
            reporte["problemas"].append(f"falta la hoja '{nombre}'")
            continue
        columnas_reales = list(crudo[nombre].columns)
        columnas_esperadas = schema.columnas(nombre)
        reporte["hojas"][nombre] = {"filas": len(crudo[nombre]), "columnas": columnas_reales}
        if columnas_reales != columnas_esperadas:
            reporte["problemas"].append(
                f"hoja '{nombre}': columnas {columnas_reales} != esperado {columnas_esperadas}"
            )

    if "config" in crudo:
        df_config = crudo["config"]
        config_publicada = dict(zip(df_config["clave"], df_config["valor"]))
        reporte["config_publicada"] = config_publicada
        for clave, esperado in VALORES_CONFIG.items():
            real = config_publicada.get(clave)
            if real != esperado:
                reporte["problemas"].append(f"config['{clave}'] = {real!r}, esperado {esperado!r}")
    else:
        reporte["problemas"].append("falta la hoja 'config'")

    reporte["ok"] = not reporte["problemas"]
    return reporte


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siembra y publica OLATATA_DB.xlsx (libro vivo de producción).")
    parser.add_argument(
        "--verify-only", action="store_true",
        help="No siembra nada; solo relee y valida lo ya publicado en GitHub.",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    repo = os.environ.get("GITHUB_REPO", GITHUB_REPO_DEFAULT)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Falta GITHUB_TOKEN en el entorno.")

    if not args.verify_only:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / LOCAL_DB_NAME
            storage = _construir_storage_real(local_path)
            with storage.transaction() as tx:
                sembrar_config(tx)
            estado = storage.sync_status()
            if estado.en_conflicto or estado.ultimo_error:
                print(json.dumps({"publicado": False, "sync_status": vars(estado)}, indent=2, ensure_ascii=False))
                return 1
            print(json.dumps({"publicado": True, "sync_status": vars(estado)}, indent=2, ensure_ascii=False))

    reporte = _leer_publicado_desde_github(repo, token)
    print(json.dumps(reporte, indent=2, ensure_ascii=False, default=str))
    return 0 if reporte["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
