import pytest

from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError, requerir, tiene_capacidad


def test_admin_puede_ver_costos():
    assert tiene_capacidad(ADMIN, "ver_costos")
    requerir(ADMIN, "ver_costos")  # no lanza


def test_vendedor_no_puede_ver_costos():
    assert not tiene_capacidad(VENDEDOR, "ver_costos")
    with pytest.raises(PermisoDenegadoError):
        requerir(VENDEDOR, "ver_costos")


def test_vendedor_no_puede_anular_venta():
    with pytest.raises(PermisoDenegadoError):
        requerir(VENDEDOR, "anular_venta")


def test_vendedor_no_puede_ajustar_stock():
    with pytest.raises(PermisoDenegadoError):
        requerir(VENDEDOR, "ajustar_stock")


def test_vendedor_no_puede_cerrar_mes():
    with pytest.raises(PermisoDenegadoError):
        requerir(VENDEDOR, "cerrar_mes")


def test_vendedor_si_puede_vender_y_hacer_devolucion_cambio():
    requerir(VENDEDOR, "vender")
    requerir(VENDEDOR, "devolucion_cambio")


def test_rol_desconocido_no_tiene_ninguna_capacidad():
    assert not tiene_capacidad("fantasma", "vender")
    with pytest.raises(PermisoDenegadoError):
        requerir("fantasma", "vender")


def test_mensaje_de_error_incluye_rol_y_capacidad():
    with pytest.raises(PermisoDenegadoError) as exc_info:
        requerir(VENDEDOR, "cerrar_mes")
    assert "vendedor" in str(exc_info.value)
    assert "cerrar_mes" in str(exc_info.value)
