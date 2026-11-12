"""Pruebas de enrutado/sesión de `app.py` (propiedad de A5).

`app.py` importa Streamlit a nivel de módulo (p.ej. `st.set_page_config`),
pero fuera de `streamlit run` esas llamadas solo registran una advertencia
("missing ScriptRunContext") y no truenan — así que el módulo se puede
importar y sus funciones puras (`decidir_pantalla`, `sesion_es_valida`)
se pueden probar directamente, sin levantar un servidor de Streamlit.
"""
from __future__ import annotations

from datetime import timedelta

import app
from core import auth
from core.timeutil import now_utc, to_iso_utc


def _crear_admin(storage, usuario="joseph", password="Clave1234"):
    with storage.transaction() as tx:
        uid = auth.crear_usuario(
            tx, nombre="Joseph", usuario=usuario, password_plano=password, rol="admin", permitir_sin_sesion=True
        )
    return uid


# ------------------------------------------------------- decidir_pantalla
def test_decidir_pantalla_sin_usuarios_va_a_primer_arranque():
    assert (
        app.decidir_pantalla(hay_usuarios=False, sesion_valida=False, must_change_password=False)
        == "primer_arranque"
    )


def test_decidir_pantalla_sin_usuarios_ignora_sesion_valida():
    # aunque hubiera (improbablemente) una sesión "válida", sin usuarios
    # creados siempre se debe pasar primero por el asistente
    assert (
        app.decidir_pantalla(hay_usuarios=False, sesion_valida=True, must_change_password=False)
        == "primer_arranque"
    )


def test_decidir_pantalla_con_usuarios_sin_sesion_va_a_login():
    assert (
        app.decidir_pantalla(hay_usuarios=True, sesion_valida=False, must_change_password=False)
        == "login"
    )


def test_decidir_pantalla_sesion_valida_con_cambio_forzado():
    assert (
        app.decidir_pantalla(hay_usuarios=True, sesion_valida=True, must_change_password=True)
        == "cambiar_password"
    )


def test_decidir_pantalla_sesion_valida_normal_va_a_app():
    assert (
        app.decidir_pantalla(hay_usuarios=True, sesion_valida=True, must_change_password=False)
        == "app"
    )


# ------------------------------------------------------------ _hay_usuarios
def test_hay_usuarios_falso_en_libro_vacio(storage):
    assert app._hay_usuarios(storage) is False


def test_hay_usuarios_verdadero_tras_crear_admin(storage):
    _crear_admin(storage)
    assert app._hay_usuarios(storage) is True


# --------------------------------------------------------- sesion_es_valida
def test_sesion_es_valida_acepta_sesion_reciente(storage):
    uid = _crear_admin(storage)
    sesion = {
        "usuario_id": uid,
        "session_epoch": 1,
        "ultima_actividad_utc": to_iso_utc(now_utc()),
    }
    assert app.sesion_es_valida(storage, sesion) is True


def test_sesion_es_valida_rechaza_epoch_desactualizado(storage):
    """Un cambio de clave incrementa `session_epoch` (core.auth); una
    sesión abierta en otro dispositivo con el epoch viejo debe forzar
    logout en el siguiente rerun (§10)."""
    uid = _crear_admin(storage)
    with storage.transaction() as tx:
        auth.cambiar_password(tx, uid, "NuevaClave999", rol_llamador="admin", llamador_id=uid)
    sesion_vieja = {
        "usuario_id": uid,
        "session_epoch": 1,  # ya no coincide (ahora es 2)
        "ultima_actividad_utc": to_iso_utc(now_utc()),
    }
    assert app.sesion_es_valida(storage, sesion_vieja) is False


def test_sesion_es_valida_rechaza_por_inactividad(storage):
    uid = _crear_admin(storage)
    hace_rato = now_utc() - timedelta(minutes=auth.SESION_MINUTOS_DEFAULT + 5)
    sesion = {
        "usuario_id": uid,
        "session_epoch": 1,
        "ultima_actividad_utc": to_iso_utc(hace_rato),
    }
    assert app.sesion_es_valida(storage, sesion) is False


def test_sesion_es_valida_respeta_sesion_minutos_configurado(storage):
    """§6: `config.sesion_minutos` debe poder acortar la expiración por
    inactividad por debajo del defecto de 8 horas."""
    uid = _crear_admin(storage)
    with storage.transaction() as tx:
        tx.set_config("sesion_minutos", "10")
    hace_15_min = now_utc() - timedelta(minutes=15)
    sesion = {
        "usuario_id": uid,
        "session_epoch": 1,
        "ultima_actividad_utc": to_iso_utc(hace_15_min),
    }
    assert app.sesion_es_valida(storage, sesion) is False


def test_sesion_es_valida_falsa_si_falta_una_clave(storage):
    # dict de sesión corrupto/incompleto: nunca debe lanzar, solo rechazar
    assert app.sesion_es_valida(storage, {}) is False


def test_construir_storage_sync_enabled_apagado_sin_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    storage = app.construir_storage()
    assert storage.sync_enabled is False
