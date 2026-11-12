"""Detección del modo demo y el aviso permanente "DATOS DE PRUEBA" (§2.d
de la continuación). Módulo nuevo y aislado a propósito: `app.py` y
`core/ui.py` son de A5 (ver `docs/CONTRATOS.md`); este archivo solo
expone la capacidad lista para que A5 la llame con una línea al inicio
de `app.py`, sin que el coordinador tenga que editar esos archivos.

Import perezoso de Streamlit (igual que `core/config.py`): este módulo
es importable y testeable sin que Streamlit esté corriendo.
"""
from __future__ import annotations

import os

AVISO_DATOS_PRUEBA = "DATOS DE PRUEBA"
MENSAJE_AVISO_DATOS_PRUEBA = (
    "DATOS DE PRUEBA — esta sesión usa el libro de demostración "
    "(100% ficticio). Nada de lo que veas aquí se publica en la nube."
)

__all__ = ["AVISO_DATOS_PRUEBA", "MENSAJE_AVISO_DATOS_PRUEBA", "demo_activo", "render_aviso_datos_prueba"]


def demo_activo() -> bool:
    """`True` solo si `DEMO=1` exactamente, igual que la compuerta de
    `scripts/seed_demo.py` — nunca por la sola presencia de la variable."""
    return os.environ.get("DEMO") == "1"


def render_aviso_datos_prueba() -> bool:
    """Si el modo demo está activo, pinta el aviso permanente y devuelve
    `True`; si no, no hace nada y devuelve `False`. Pensado para que
    `app.py` lo llame una sola vez, antes de enrutar a cualquier vista:

        from core.demo_mode import render_aviso_datos_prueba
        render_aviso_datos_prueba()
    """
    if not demo_activo():
        return False
    import streamlit as st

    st.warning(MENSAJE_AVISO_DATOS_PRUEBA, icon=":material/science:")
    return True
