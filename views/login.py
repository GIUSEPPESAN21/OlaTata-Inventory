"""Vista: Login. Propiedad de A5 (SHELL/TEMA/AJUSTES). Contrato: `render(ctx)`.

Formulario usuario/clave. Mensaje de error SIEMPRE genérico (lo decide
`core.auth.login`, aquí solo se muestra tal cual — nunca se revela si el
usuario existe o no, §10). Al autenticar con éxito, guarda la sesión en
`st.session_state` y pide un rerun; `app.py` se encarga de decidir la
siguiente pantalla (cambio de clave forzado o menú principal).
"""
from __future__ import annotations

import streamlit as st

import logging
import time

from core import auth, seguridad
from core.timeutil import now_utc, to_iso_utc
from core.ui import card, encabezado_marca, mensaje_error_amable, pie_pagina, titulo_seccion
from views import ViewContext


_logger = logging.getLogger("olatata.seguridad")
_esperar = time.sleep  # punto de sustitución para las pruebas


def _registrar_ingreso(ctx: ViewContext, usuario_id: str) -> None:
    """Deja constancia del ingreso en `auditoria`. Si falla (sin red), el
    ingreso NO se bloquea: queda en el log del servidor."""
    try:
        with ctx.storage.transaction() as tx:
            seguridad.registrar_evento(tx, usuario_id, "ingreso", "inicio de sesión")
    except Exception:
        _logger.exception("no se pudo registrar el ingreso de %s en auditoría", usuario_id)


def render(ctx: ViewContext) -> None:
    encabezado_marca(subtitulo="Inventario y ventas")

    with card(acento="superior", key="ot-card-login"):
        titulo_seccion("Ingresar")
        with st.form("formulario_login", clear_on_submit=False):
            usuario = st.text_input("Usuario", icon=":material/person:")
            password = st.text_input("Contraseña", type="password", icon=":material/lock:")
            entrar = st.form_submit_button("Entrar", use_container_width=True, type="primary")

    if entrar:
        # Freno a la fuerza bruta en ESTA sesión del navegador (además del
        # bloqueo de 15 min por usuario de core.auth): 0, 0, 1, 2, 4, 8 s…
        pausa = seguridad.pausa_tras_fallos(st.session_state.get("_ot_login_fallos", 0))
        if pausa:
            _esperar(pausa)
        if not usuario or not password:
            st.error("Usuario o contraseña incorrectos.")
        else:
            try:
                resultado = auth.login(ctx.storage, usuario, password)
            except Exception as exc:  # nunca mostrar una traza de Python (§6)
                mensaje, _codigo = mensaje_error_amable(exc, contexto="login")
                st.error(mensaje)
            else:
                if resultado.ok:
                    u = resultado.usuario
                    st.session_state.pop("_ot_login_fallos", None)
                    _registrar_ingreso(ctx, u.id)
                    ahora = to_iso_utc(now_utc())
                    st.session_state["sesion"] = {
                        "usuario_id": u.id,
                        "nombre": u.nombre,
                        "usuario": u.usuario,
                        "rol": u.rol,
                        "session_epoch": u.session_epoch,
                        "must_change_password": u.must_change_password,
                        "ultima_actividad_utc": ahora,
                        "inicio_utc": ahora,
                    }
                    ctx.rerun()
                else:
                    st.session_state["_ot_login_fallos"] = st.session_state.get("_ot_login_fallos", 0) + 1
                    _logger.warning("login fallido usuario=%r fallos_sesion=%s", usuario.strip()[:60],
                                    st.session_state["_ot_login_fallos"])
                    st.error(resultado.motivo)

    pie_pagina()
