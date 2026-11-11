"""Smoke test: las vistas de VENTAS importan sin errores y exponen
`render(ctx)` (contrato de `views/__init__.py`). No se invoca `render`
directamente aquí porque requiere un runtime real de Streamlit."""
from __future__ import annotations

import inspect

from views import vender, ventas


def test_vender_expone_render_con_la_firma_del_contrato():
    assert callable(vender.render)
    firma = inspect.signature(vender.render)
    assert list(firma.parameters) == ["ctx"]


def test_ventas_expone_render_con_la_firma_del_contrato():
    assert callable(ventas.render)
    firma = inspect.signature(ventas.render)
    assert list(firma.parameters) == ["ctx"]
