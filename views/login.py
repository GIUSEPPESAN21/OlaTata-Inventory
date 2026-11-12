"""Vista: Login. Propiedad de A5 (SHELL/TEMA/AJUSTES). Contrato: `render(ctx)`.

Formulario usuario/clave. Mensaje de error SIEMPRE genérico (lo decide
`core.auth.login`, aquí solo se muestra tal cual — nunca se revela si el
usuario existe o no, §10). Al autenticar con éxito, guarda la sesión en
`st.session_state` y pide un rerun; `app.py` se encarga de decidir la
siguiente pantalla (cambio de clave forzado o menú principal).
"""
from __future__ import annotations

import streamlit as st

from core import auth
from core.timeutil import now_utc, to_iso_utc
from core.ui import card, encabezado_marca, mensaje_error_amable, pie_pagina, titulo_seccion
from views import ViewContext


def render(ctx: ViewContext) -> None:
    encabezado_marca(subtitulo="Inventario y ventas")

    with card(acento="superior", key="ot-card-login"):
        titulo_seccion("Ingresar")
        with st.form("formulario_login", clear_on_submit=False):
            usuario = st.text_input("Usuario", icon=":material/person:")
            password = st.text_input("Contraseña", type="password", icon=":material/lock:")
            entrar = st.form_submit_button("Entrar", use_container_width=True, type="primary")

    if entrar:
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
                    st.session_state["sesion"] = {
                        "usuario_id": u.id,
                        "nombre": u.nombre,
                        "usuario": u.usuario,
                        "rol": u.rol,
                        "session_epoch": u.session_epoch,
                        "must_change_password": u.must_change_password,
                        "ultima_actividad_utc": to_iso_utc(now_utc()),
                    }
                    ctx.rerun()
                else:
                    st.error(resultado.motivo)

    pie_pagina()
