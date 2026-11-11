"""Pruebas de `views.vistas_visibles_para_rol` (contrato congelado,
`views/__init__.py`) desde la óptica de A5: el menú lateral debe quedar
filtrado correctamente por rol antes de llegar a `app.py`."""
from __future__ import annotations

from core.permissions import ADMIN, VENDEDOR
from views import VIEWS, vistas_visibles_para_rol


def test_hay_maximo_cinco_vistas_en_el_menu():
    assert len(VIEWS) <= 5


def test_admin_ve_ajustes():
    claves = [v["key"] for v in vistas_visibles_para_rol(ADMIN)]
    assert "ajustes" in claves


def test_vendedor_no_ve_ajustes():
    claves = [v["key"] for v in vistas_visibles_para_rol(VENDEDOR)]
    assert "ajustes" not in claves


def test_vendedor_no_ve_inventario():
    claves = [v["key"] for v in vistas_visibles_para_rol(VENDEDOR)]
    assert "inventario" not in claves


def test_vendedor_ve_vender_y_ventas():
    claves = [v["key"] for v in vistas_visibles_para_rol(VENDEDOR)]
    assert "vender" in claves
    assert "ventas" in claves


def test_admin_ve_todas_las_vistas_cuyo_permiso_tiene():
    """OJO (hallazgo, no se corrige aquí): `core.permissions.CAPABILITIES`
    le da a `admin` la capacidad `ver_analisis_completo` pero NO
    `ver_analisis_basico`, que es la que exige `views.VIEWS` para la
    pantalla "Análisis" — así que con el contrato actual el admin NO ve
    esa pantalla en el menú. Reportado en el informe final como un
    contrato a revisar; esta prueba documenta el comportamiento real."""
    claves = [v["key"] for v in vistas_visibles_para_rol(ADMIN)]
    assert claves == ["vender", "ventas", "inventario", "ajustes"]
    assert "analisis" not in claves


def test_rol_desconocido_no_ve_nada():
    assert vistas_visibles_para_rol("fantasma") == []


def test_cada_vista_tiene_un_solo_emoji_de_icono():
    # §9: máximo un emoji por ítem de menú
    for vista in VIEWS:
        assert len(vista["icon"]) <= 2  # un emoji puede ocupar 1-2 code points
