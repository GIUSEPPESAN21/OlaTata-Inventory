"""§2.d: la app debe mostrar el aviso permanente "DATOS DE PRUEBA" cuando
DEMO=1. `core.demo_mode` es la capacidad ya lista para que A5 la llame
desde `app.py` con una línea; estas pruebas la verifican de forma
aislada (sin levantar Streamlit de verdad)."""
from __future__ import annotations

import sys
import types

from core.demo_mode import MENSAJE_AVISO_DATOS_PRUEBA, demo_activo, render_aviso_datos_prueba


def test_demo_activo_es_false_por_defecto(monkeypatch):
    monkeypatch.delenv("DEMO", raising=False)
    assert demo_activo() is False


def test_demo_activo_solo_con_el_valor_exacto_1(monkeypatch):
    monkeypatch.setenv("DEMO", "true")
    assert demo_activo() is False
    monkeypatch.setenv("DEMO", "1")
    assert demo_activo() is True


def test_render_aviso_no_hace_nada_sin_demo(monkeypatch):
    monkeypatch.delenv("DEMO", raising=False)
    assert render_aviso_datos_prueba() is False


def test_render_aviso_pinta_el_mensaje_con_demo_activo(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    llamadas: list[tuple[str, dict]] = []
    streamlit_falso = types.SimpleNamespace(warning=lambda msg, **kw: llamadas.append((msg, kw)))
    monkeypatch.setitem(sys.modules, "streamlit", streamlit_falso)

    assert render_aviso_datos_prueba() is True
    assert llamadas == [(MENSAJE_AVISO_DATOS_PRUEBA, {"icon": ":material/science:"})]
