"""Contrato de claves de CONFIG (§1 de la continuación): falla si algún
módulo de producción lee o escribe una clave de `CONFIG` literal que no
está documentada en `core/config_keys.py` / `docs/CONTRATOS.md`.

Solo escanea código de PRODUCCIÓN (app.py, core/, views/, scripts/) —
las pruebas mismas usan claves de prueba genéricas ("x", "a", ...) para
ejercitar el primitivo `get_config`/`set_config` y no deben confundirse
con claves de negocio reales.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.config_keys import CLAVES_CONOCIDAS, es_clave_conocida

REPO_ROOT = Path(__file__).resolve().parent.parent

ARCHIVOS_DE_PRODUCCION = (
    [REPO_ROOT / "app.py"]
    + sorted((REPO_ROOT / "core").glob("*.py"))
    + sorted((REPO_ROOT / "views").glob("*.py"))
    + sorted((REPO_ROOT / "scripts").glob("*.py"))
)

_MÉTODOS_DE_CONFIG = {"get_config", "set_config"}


def _claves_literales_usadas(path: Path) -> list[tuple[str, int]]:
    """Devuelve [(clave, linea), ...] de toda llamada `algo.get_config("x")`
    o `algo.set_config("x", ...)` cuyo primer argumento sea un string
    literal. Las llamadas con variable (p.ej. `tx.set_config(clave, ...)`
    dentro de un bucle) no se pueden verificar estáticamente y se omiten
    a propósito — no son un falso positivo, simplemente no son
    verificables sin ejecutar el código."""
    arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    encontradas: list[tuple[str, int]] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        func = nodo.func
        if not (isinstance(func, ast.Attribute) and func.attr in _MÉTODOS_DE_CONFIG):
            continue
        if not nodo.args:
            continue
        primer_arg = nodo.args[0]
        if isinstance(primer_arg, ast.Constant) and isinstance(primer_arg.value, str):
            encontradas.append((primer_arg.value, nodo.lineno))
    return encontradas


@pytest.mark.parametrize("path", ARCHIVOS_DE_PRODUCCION, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_toda_clave_de_config_literal_esta_documentada(path: Path):
    desconocidas = [
        (clave, linea) for clave, linea in _claves_literales_usadas(path) if not es_clave_conocida(clave)
    ]
    assert not desconocidas, (
        f"{path.relative_to(REPO_ROOT)} usa clave(s) de CONFIG no documentadas en "
        f"core/config_keys.py: {desconocidas}"
    )


def test_core_config_keys_no_esta_vacio():
    assert len(CLAVES_CONOCIDAS) >= 8


def test_contratos_md_menciona_cada_clave_conocida():
    texto = (REPO_ROOT / "docs" / "CONTRATOS.md").read_text(encoding="utf-8")
    faltantes = [clave for clave in CLAVES_CONOCIDAS if clave not in texto]
    assert not faltantes, f"docs/CONTRATOS.md no menciona: {faltantes}"
