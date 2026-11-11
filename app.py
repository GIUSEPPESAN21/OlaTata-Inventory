"""Ola Tata · Inventario y Ventas — enrutado y sesión.

Propiedad EXCLUSIVA de A5 (SHELL/TEMA/AJUSTES). Este módulo SOLO hace
enrutado y manejo de sesión: nunca contiene lógica de negocio. Las
pantallas vienen del registro `views.VIEWS` (contrato congelado) y cada
módulo de vista expone `render(ctx)` — así este archivo no necesita
cambiar cuando A1-A4 completen el contenido real de su vista (hasta
entonces siguen siendo el stub "en construcción").

Flujo (§6, §10):
1. Si la hoja `usuarios` está vacía -> asistente de primer arranque.
2. Si no hay sesión válida en `st.session_state` -> login.
3. `core.auth.validar_sesion` se revalida en CADA rerun (expira por
   inactividad o si cambió el `session_epoch`, p.ej. tras un cambio de
   clave en otra pestaña) -> si es inválida, fuerza logout.
4. Si la sesión es válida pero `must_change_password` -> cambio forzado.
5. En otro caso, pinta el menú lateral (máx. 5, filtrado por rol vía
   `vistas_visibles_para_rol`) y renderiza la vista seleccionada.
"""
from __future__ import annotations

import importlib

import streamlit as st

from core import auth, schema
from core.config import DEFAULT_DB_PATH, safe_secret
from core.permissions import ADMIN, PermisoDenegadoError
from core.storage import Storage
from core.timeutil import now_utc, parse_iso_utc, to_iso_utc
from core.ui import encabezado_marca, mensaje_error_amable, pie_pagina, validar_password
from views import ViewContext, vistas_visibles_para_rol

st.set_page_config(page_title="Ola Tata · Inventario y Ventas", page_icon="👜", layout="wide")


# ----------------------------------------------------------- lógica pura
def decidir_pantalla(*, hay_usuarios: bool, sesion_valida: bool, must_change_password: bool) -> str:
    """Decide qué pantalla mostrar. Función pura (sin Streamlit), testeable
    directamente — ver `tests/test_ui_routing.py`."""
    if not hay_usuarios:
        return "primer_arranque"
    if not sesion_valida:
        return "login"
    if must_change_password:
        return "cambiar_password"
    return "app"


def construir_storage() -> Storage:
    """Arma `Storage` leyendo los secretos de GitHub con `safe_secret`
    (nunca truena si no hay `secrets.toml`, p.ej. al correr en local por
    primera vez). Sin token -> `sync_enabled=False` automáticamente."""
    github_repo = safe_secret("GITHUB_REPO")
    github_token = safe_secret("GITHUB_TOKEN")
    archive_repo = safe_secret("GITHUB_REPO_ARCHIVE")
    return Storage(
        local_path=DEFAULT_DB_PATH,
        github_repo=github_repo,
        github_token=github_token,
        archive_repo=archive_repo,
        sync_enabled=bool(github_token),
    )


def sesion_es_valida(storage, sesion: dict) -> bool:
    """Envoltorio de `core.auth.validar_sesion` sobre el diccionario de
    sesión guardado en `st.session_state`. Lee `config.sesion_minutos`
    (editable desde Ajustes) si está configurado; si no, usa el defecto
    de `core.auth.SESION_MINUTOS_DEFAULT`."""
    try:
        minutos_config = storage.get_config("sesion_minutos")
        minutos_inactividad = int(minutos_config) if minutos_config else None
    except Exception:
        minutos_inactividad = None
    try:
        return auth.validar_sesion(
            storage,
            sesion["usuario_id"],
            sesion["session_epoch"],
            parse_iso_utc(sesion["ultima_actividad_utc"]),
            minutos_inactividad=minutos_inactividad,
        )
    except Exception:
        return False


# -------------------------------------------------------- estado/sesión
@st.cache_resource(show_spinner=False)
def _storage_singleton() -> Storage:
    return construir_storage()


def _hay_usuarios(storage) -> bool:
    return not storage.read_sheet(schema.USUARIOS).empty


def _sesion_actual() -> dict | None:
    return st.session_state.get("sesion")


def _cerrar_sesion() -> None:
    st.session_state.pop("sesion", None)


def _tocar_actividad(sesion: dict) -> None:
    sesion["ultima_actividad_utc"] = to_iso_utc(now_utc())


# --------------------------------------------------------------- vistas
def _vista_cambiar_password(storage, sesion: dict) -> None:
    encabezado_marca()
    st.subheader("Cambia tu contraseña")
    st.write("Por seguridad debes elegir una contraseña nueva antes de continuar.")
    with st.form("formulario_cambiar_password"):
        nueva = st.text_input("Contraseña nueva", type="password")
        repetir = st.text_input("Repite la contraseña nueva", type="password")
        enviar = st.form_submit_button("Guardar", use_container_width=True)
    if enviar:
        error = validar_password(nueva)
        if error:
            st.error(error)
        elif nueva != repetir:
            st.error("Las dos contraseñas no coinciden.")
        else:
            try:
                with storage.transaction() as tx:
                    auth.cambiar_password(tx, sesion["usuario_id"], nueva)
            except Exception as exc:  # nunca una traza de Python visible (§6)
                mensaje, _codigo = mensaje_error_amable(exc, contexto="cambiar_password")
                st.error(mensaje)
            else:
                st.success("Contraseña actualizada. Ingresa de nuevo con tu clave nueva.")
                _cerrar_sesion()
                st.rerun()
    pie_pagina()


def _render_app(storage, sesion: dict) -> None:
    rol = sesion["rol"]
    vistas = vistas_visibles_para_rol(rol)

    with st.sidebar:
        encabezado_marca()
        etiqueta_rol = "Administrador" if rol == ADMIN else "Vendedor"
        st.caption(f"{sesion['nombre']} · {etiqueta_rol}")

        if not vistas:
            st.warning("Tu usuario no tiene pantallas asignadas todavía.")
            if st.button("Cerrar sesión", use_container_width=True):
                _cerrar_sesion()
                st.rerun()
            pie_pagina()
            return

        claves = [v["key"] for v in vistas]
        etiquetas = {v["key"]: f"{v['icon']} {v['label']}" for v in vistas}
        vista_guardada = st.session_state.get("vista_actual")
        if vista_guardada not in claves:
            vista_guardada = claves[0]
        seleccion = st.radio(
            "Menú",
            options=claves,
            index=claves.index(vista_guardada),
            format_func=lambda k: etiquetas[k],
            label_visibility="collapsed",
        )
        st.session_state["vista_actual"] = seleccion

        if st.button("Cerrar sesión", use_container_width=True):
            _cerrar_sesion()
            st.rerun()
        pie_pagina()

    vista = next(v for v in vistas if v["key"] == seleccion)
    usuario = auth.Usuario(
        id=sesion["usuario_id"],
        nombre=sesion["nombre"],
        usuario=sesion["usuario"],
        rol=rol,
        activo=True,
        must_change_password=False,
        session_epoch=sesion["session_epoch"],
    )
    ctx = ViewContext(storage=storage, usuario=usuario, rerun=st.rerun)
    try:
        modulo = importlib.import_module(vista["module"])
        modulo.render(ctx)
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esta acción: {exc}")
    except Exception as exc:  # nunca una traza de Python visible (§6)
        mensaje, _codigo = mensaje_error_amable(exc, contexto=f"vista:{vista['key']}")
        st.error(mensaje)


# ----------------------------------------------------------------- main
def main() -> None:
    storage = _storage_singleton()

    hay_usuarios = _hay_usuarios(storage)
    sesion = _sesion_actual()
    sesion_valida = sesion is not None and sesion_es_valida(storage, sesion)
    if sesion is not None and not sesion_valida:
        _cerrar_sesion()
        sesion = None

    must_change_password = bool(sesion["must_change_password"]) if sesion_valida and sesion else False

    pantalla = decidir_pantalla(
        hay_usuarios=hay_usuarios,
        sesion_valida=sesion_valida,
        must_change_password=must_change_password,
    )

    if pantalla == "primer_arranque":
        from views import primer_arranque

        primer_arranque.render(ViewContext(storage=storage, usuario=None, rerun=st.rerun))
        return

    if pantalla == "login":
        from views import login

        login.render(ViewContext(storage=storage, usuario=None, rerun=st.rerun))
        return

    _tocar_actividad(sesion)

    if pantalla == "cambiar_password":
        _vista_cambiar_password(storage, sesion)
        return

    _render_app(storage, sesion)


if __name__ == "__main__":
    main()
