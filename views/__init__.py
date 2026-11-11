"""Registro de vistas — CONTRATO CONGELADO (ver docs/CONTRATOS.md).

Cada entrada describe una pantalla del menú lateral (máx. 5, §6). Cada
módulo de vista expone una función `render(ctx)` donde `ctx` es un
`ViewContext` (ver abajo). Así `app.py` (propiedad exclusiva de A5) nunca
necesita cambiar cuando A1-A4 implementan el contenido real de su vista:
solo importa el módulo que ya existe aquí como stub.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ViewContext:
    """Lo que cada vista recibe de `app.py` para renderizarse.

    `storage`: instancia de `core.storage.Storage` (o `FakeStorage` en
    pruebas). `usuario`: `core.auth.Usuario` ya autenticado. `rerun`:
    callback para forzar un refresco de Streamlit tras una acción.
    """

    storage: Any
    usuario: Any
    rerun: Callable[[], None]


VIEWS: list[dict[str, str]] = [
    {"key": "vender", "label": "Vender", "icon": "🛍️", "module": "views.vender", "permiso": "vender"},
    {"key": "ventas", "label": "Ventas", "icon": "🧾", "module": "views.ventas", "permiso": "vender"},
    {"key": "inventario", "label": "Inventario", "icon": "📦", "module": "views.inventario", "permiso": "gestionar_inventario"},
    {"key": "analisis", "label": "Análisis", "icon": "📊", "module": "views.analisis", "permiso": "ver_analisis_basico"},
    {"key": "ajustes", "label": "Ajustes", "icon": "⚙️", "module": "views.ajustes", "permiso": "configurar_negocio"},
]


def vistas_visibles_para_rol(rol: str) -> list[dict[str, str]]:
    """Filtra `VIEWS` a las que el rol puede siquiera abrir (revalidación
    real de permisos ocurre además dentro de cada función de core/, §10)."""
    from core.permissions import tiene_capacidad

    return [vista for vista in VIEWS if tiene_capacidad(rol, vista["permiso"])]
