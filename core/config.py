"""Acceso seguro a secretos/configuración (patrón del lab, R1).

`st.secrets` lanza una excepción si NO existe ningún `secrets.toml` en
absoluto (no solo cuando falta una clave puntual). `safe_secret` envuelve
ese acceso para que nunca truene, con fallback a variables de entorno.
Import perezoso de streamlit: este módulo es importable y testeable sin
que Streamlit esté corriendo.
"""
from __future__ import annotations

import os

DEFAULT_DB_PATH = "OLATATA_DB.xlsx"

__all__ = ["safe_secret", "DEFAULT_DB_PATH"]


def safe_secret(key: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st

        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
    except ImportError:
        pass
    return os.environ.get(key, default)
