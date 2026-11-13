"""Vista: Primer arranque. Propiedad de A5 (SHELL/TEMA/AJUSTES).

Se muestra únicamente cuando la hoja `usuarios` está vacía (ningún
usuario creado todavía). Asistente de un solo paso: crea el admin con
`must_change_password=True` (§6) para que el cambio de clave sea forzado
en el primer ingreso real.
"""
from __future__ import annotations

import streamlit as st

from core import auth, seguridad
from core.ui import (
    card,
    encabezado_marca,
    generar_password_temporal,
    mensaje_error_amable,
    pie_pagina,
    titulo_seccion,
    validar_password,
)
from views import ViewContext


def render(ctx: ViewContext) -> None:
    encabezado_marca(subtitulo="Primer arranque")

    if "clave_temporal_sugerida" not in st.session_state:
        st.session_state["clave_temporal_sugerida"] = generar_password_temporal()

    with card(acento="superior", key="ot-card-primer-arranque"):
        titulo_seccion("Bienvenido")
        st.write(
            "Todavía no hay ningún usuario creado. Crea la cuenta de "
            "administrador del negocio para empezar."
        )

        with st.form("formulario_primer_arranque"):
            nombre = st.text_input("Tu nombre completo", icon=":material/badge:")
            usuario = st.text_input("Usuario con el que vas a ingresar", icon=":material/person:")
            modo_clave = st.radio(
                "Contraseña temporal",
                options=["Usar una generada automáticamente", "Elegir una propia"],
                index=0,
            )
            if modo_clave == "Usar una generada automáticamente":
                st.code(st.session_state["clave_temporal_sugerida"])
                clave_elegida = st.session_state["clave_temporal_sugerida"]
            else:
                clave_elegida = st.text_input("Contraseña temporal", type="password", icon=":material/lock:")

            st.caption("Se te pedirá cambiarla la primera vez que ingreses.")
            crear = st.form_submit_button("Crear administrador", use_container_width=True, type="primary")

    if crear:
        errores = []
        if not nombre.strip():
            errores.append("Escribe tu nombre.")
        if not usuario.strip():
            errores.append("Escribe un usuario.")
        error_password = validar_password(clave_elegida or "", usuario=usuario.strip(), nombre=nombre.strip())
        if error_password:
            errores.append(error_password)

        if errores:
            for err in errores:
                st.error(err)
            return

        try:
            with ctx.storage.transaction() as tx:
                nuevo_id = auth.crear_usuario(
                    tx,
                    nombre=nombre.strip(),
                    usuario=usuario.strip(),
                    password_plano=clave_elegida,
                    rol="admin",
                    must_change_password=True,
                    permitir_sin_sesion=True,
                )
                seguridad.registrar_evento(tx, nuevo_id, "crear_admin", f"usuario={usuario.strip()} (primer arranque)")
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:  # nunca una traza de Python visible (§6)
            mensaje, _codigo = mensaje_error_amable(exc, contexto="primer_arranque")
            st.error(mensaje)
        else:
            st.session_state.pop("clave_temporal_sugerida", None)
            st.success("Administrador creado. Ya puedes ingresar.")
            ctx.rerun()

    pie_pagina()
