"""Pruebas de `core/ui.py`: helpers de presentación puros (sin Streamlit
corriendo). Propiedad de A5 (SHELL/TEMA/AJUSTES)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core import ui


def test_validar_password_rechaza_corta():
    assert ui.validar_password("Abc12345") is not None  # 8 < 10 caracteres


def test_validar_password_acepta_clave_robusta():
    assert ui.validar_password("Cartera7Rosa") is None


def test_validar_password_aplica_politica_de_usuario_y_nombre():
    assert ui.validar_password("mariaperez2026", usuario="mariap", nombre="María Perez") is not None


def test_generar_password_temporal_largo_y_alfabeto():
    clave = ui.generar_password_temporal()
    assert len(clave) >= ui.PASSWORD_MIN_LENGTH
    assert clave.isalnum()


def test_generar_password_temporal_longitud_minima_forzada():
    # aunque se pida algo más corto que el mínimo, nunca se entrega así
    clave = ui.generar_password_temporal(longitud=3)
    assert len(clave) >= ui.PASSWORD_MIN_LENGTH


def test_generar_password_temporal_no_se_repite_trivialmente():
    claves = {ui.generar_password_temporal() for _ in range(20)}
    assert len(claves) > 1  # aleatorio, no determinista


def test_generar_codigo_incidente_formato():
    codigo = ui.generar_codigo_incidente()
    assert codigo.startswith("INC-")
    assert len(codigo) == len("INC-") + 8


def test_mensaje_error_amable_nunca_expone_traza_python():
    exc = ValueError("detalle sensible interno de una traza")
    mensaje, codigo = ui.mensaje_error_amable(exc, contexto="prueba")
    assert "detalle sensible interno de una traza" not in mensaje
    assert codigo in mensaje
    assert mensaje.startswith("Ocurrió un problema inesperado.")


def test_formatear_fecha_hora_local_convierte_a_bogota():
    # 04:30 UTC del 11-nov == 23:30 de Bogotá del 10-nov (UTC-5, R2)
    dt_utc = datetime(2026, 11, 11, 4, 30, tzinfo=timezone.utc)
    texto = ui.formatear_fecha_hora_local(dt_utc)
    assert "10/11/2026" in texto
    assert "11:30" in texto
    assert "p.m." in texto


def test_formatear_fecha_hora_local_acepta_naive_como_utc():
    dt_naive = datetime(2026, 11, 11, 15, 0)  # sin tzinfo, se asume UTC
    texto = ui.formatear_fecha_hora_local(dt_naive)
    assert "11/11/2026" in texto


@dataclass
class _FakeSyncStatus:
    pendientes: int = 0
    en_conflicto: bool = False
    ultimo_error: str | None = None
    ultimo_sync_utc: str | None = None


def test_resumen_estado_sync_todo_sincronizado():
    resumen = ui.resumen_estado_sync(_FakeSyncStatus())
    assert resumen["categoria"] == "exito"


def test_resumen_estado_sync_pendientes():
    resumen = ui.resumen_estado_sync(_FakeSyncStatus(pendientes=3))
    assert resumen["categoria"] == "alerta"
    assert "3" in resumen["texto"]


def test_resumen_estado_sync_conflicto_tiene_prioridad():
    resumen = ui.resumen_estado_sync(_FakeSyncStatus(pendientes=5, en_conflicto=True))
    assert resumen["categoria"] == "error"


def test_confirmacion_coincide_ignora_mayusculas_y_espacios():
    assert ui.confirmacion_coincide("joseph", "  Joseph  ")
    assert not ui.confirmacion_coincide("joseph", "otro")
    assert not ui.confirmacion_coincide("joseph", "")


def test_confirmacion_coincide_falsa_si_falta_alguno():
    assert not ui.confirmacion_coincide(None, "joseph")
    assert not ui.confirmacion_coincide("joseph", None)


# ---------------------------------------------------------------- pintado
# Fuera de `streamlit run` estas llamadas a `st.*` solo registran una
# advertencia ("missing ScriptRunContext") y no truenan — sirve para
# verificar que las funciones de pintado no lancen ninguna excepción con
# argumentos válidos, sin necesitar un servidor de Streamlit real.
def test_tarjeta_kpi_no_truena_sin_streamlit_corriendo():
    ui.tarjeta_kpi("Ventas del día", "$ 150.000")


def test_tarjeta_kpi_pesos_usa_format_cop():
    ui.tarjeta_kpi_pesos("Ganancia", 50000, delta="+10%")


def test_estado_vacio_no_truena():
    ui.estado_vacio("Todavía no hay nada aquí.", "Agrega tu primer producto.")


def test_pie_pagina_no_truena():
    ui.pie_pagina()


def test_inyectar_identidad_visual_no_truena():
    ui.inyectar_identidad_visual()


def test_encabezado_marca_no_truena():
    ui.encabezado_marca("Ola Tata")
