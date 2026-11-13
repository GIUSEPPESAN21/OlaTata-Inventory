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

import html
import importlib

import streamlit as st

from core import auth, schema, seguridad
from core.config import DEFAULT_DB_PATH, safe_secret
from core.config_inicial import claves_faltantes, completar_config_faltante
from core.demo_mode import demo_activo, render_aviso_datos_prueba
from core.permissions import MAESTRO, PermisoDenegadoError, nombre_rol
from core.storage import BaseDeDatosNoDisponibleError, Storage
from core.timeutil import now_utc, parse_iso_utc, to_iso_utc
from core.ui import (
    ICONOS_VISTA,
    card,
    chip_estado,
    encabezado_marca,
    logo_path,
    mensaje_error_amable,
    pie_pagina,
    reiniciar_identidad_visual_para_este_rerun,
    resumen_estado_sync,
    titulo_seccion,
    validar_password,
)
from views import ViewContext, vistas_visibles_para_rol

# A3/A2: favicon real generado por `scripts/build_logo_assets.py`. Si el
# entorno todavía no corrió ese script (p.ej. un checkout nuevo), se
# degrada al emoji anterior en vez de tronar `st.set_page_config`.
_FAVICON = logo_path("favicon-32.png") or "👜"
st.set_page_config(page_title="Ola Tata · Inventario y Ventas", page_icon=_FAVICON, layout="wide")


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


_DEFAULT_DEMO_DB_PATH = "demo/OLATATA_DEMO.xlsx"


def construir_storage() -> Storage:
    """Arma `Storage` leyendo los secretos de GitHub con `safe_secret`
    (nunca truena si no hay `secrets.toml`, p.ej. al correr en local por
    primera vez). Sin token -> `sync_enabled=False` automáticamente.

    Modo demo (`DEMO=1`, ver `core.demo_mode`): apunta `local_path` al
    libro de demostración en vez de a `OLATATA_DB.xlsx` (por defecto
    `demo/OLATATA_DEMO.xlsx`, el mismo que escribe
    `scripts/seed_demo.py`; override con la variable de entorno
    `OLATATA_DB_PATH` si se quiere otra ruta) y FUERZA
    `sync_enabled=False` sin importar si hay `GITHUB_TOKEN` configurado
    en esta máquina — defensa en profundidad para nunca publicar datos
    de prueba a la nube, igual que `scripts/seed_demo.py`."""
    if demo_activo():
        local_path = safe_secret("OLATATA_DB_PATH", _DEFAULT_DEMO_DB_PATH) or _DEFAULT_DEMO_DB_PATH
        return Storage(
            local_path=local_path,
            github_repo=None,
            github_token=None,
            archive_repo=None,
            sync_enabled=False,
        )

    github_repo = safe_secret("GITHUB_REPO")
    github_token = safe_secret("GITHUB_TOKEN")
    archive_repo = safe_secret("GITHUB_REPO_ARCHIVE")
    local_path = safe_secret("OLATATA_DB_PATH", DEFAULT_DB_PATH) or DEFAULT_DB_PATH
    return Storage(
        local_path=local_path,
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
    if seguridad.sesion_excede_maximo(sesion.get("inicio_utc")):
        return False  # duración máxima absoluta, aunque haya actividad
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


def _autorreparar_config(storage) -> None:
    """Restaura las claves de configuración del negocio que falten en la
    base (p.ej. si una versión vieja de la app publicó un libro vacío).
    Solo agrega lo que falta; nunca pisa un valor editado. Se intenta una
    vez por proceso: si falla (sin red), la app sigue funcionando igual."""
    if st.session_state.get("_ot_config_revisada"):
        return
    st.session_state["_ot_config_revisada"] = True
    try:
        if claves_faltantes(storage):
            with storage.transaction() as tx:
                completar_config_faltante(tx)
        # Debe existir un maestro: si no, el primer administrador lo es.
        usuarios = storage.read_sheet(schema.USUARIOS)
        if not ((usuarios["rol"] == MAESTRO) & usuarios["activo"].astype(bool)).any():
            with storage.transaction() as tx:
                seguridad.asegurar_maestro(tx)
    except Exception as exc:  # nunca bloquear el arranque por esto
        mensaje_error_amable(exc, contexto="autorreparar_config")


def _vista_base_no_disponible() -> None:
    encabezado_marca(subtitulo="Inventario y ventas")
    with card(acento="superior", key="ot-card-sin-conexion"):
        titulo_seccion("Sin conexión con la base de datos")
        st.write(
            "No pudimos abrir la base de datos en la nube (GitHub). Tus datos "
            "están a salvo: la app no arranca con una base vacía para no "
            "sobrescribirlos. Revisa la conexión a internet y vuelve a intentar."
        )
        st.caption(
            "Si el problema continúa, el administrador debe revisar que el token "
            "(GITHUB_TOKEN) siga vigente en los Secrets de la app."
        )
        if st.button("Reintentar", type="primary", use_container_width=True, icon=":material/refresh:"):
            st.rerun()
    pie_pagina()


def _indicador_conexion(storage) -> None:
    """Chip discreto en la barra lateral: nube sincronizada / pendiente /
    conflicto / modo local. Texto + icono, nunca solo color."""
    if not getattr(storage, "sync_enabled", False):
        html = chip_estado("Modo local (sin nube)", "info", icono="computer")
    else:
        resumen = resumen_estado_sync(storage.sync_status())
        textos = {
            "exito": ("Base en la nube al día", "cloud_done"),
            "alerta": ("Cambios por sincronizar", "cloud_upload"),
            "error": ("Conflicto de sincronización", "cloud_off"),
        }
        texto, icono = textos.get(resumen["categoria"], ("Base en la nube", "cloud"))
        html = chip_estado(texto, resumen["categoria"], icono=icono)
    st.markdown(f'<div class="ot-indicador-conexion">{html}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------- vistas
def _vista_cambiar_password(storage, sesion: dict) -> None:
    encabezado_marca(subtitulo="Inventario y ventas")
    with card(acento="superior", key="ot-card-login-cambio"):
        titulo_seccion("Cambia tu contraseña")
        st.caption(
            "Por seguridad debes elegir una contraseña nueva antes de continuar: al menos "
            f"{seguridad.PASSWORD_MIN} caracteres, con letras y números, y que no incluya tu nombre ni tu usuario."
        )
        with st.form("formulario_cambiar_password"):
            nueva = st.text_input("Contraseña nueva", type="password", icon=":material/lock:")
            repetir = st.text_input("Repite la contraseña nueva", type="password", icon=":material/lock:")
            enviar = st.form_submit_button("Guardar", use_container_width=True, type="primary")
    if enviar:
        error = validar_password(nueva, usuario=sesion.get("usuario"), nombre=sesion.get("nombre"))
        if error:
            st.error(error)
        elif nueva != repetir:
            st.error("Las dos contraseñas no coinciden.")
        else:
            try:
                with storage.transaction() as tx:
                    auth.cambiar_password(
                        tx,
                        sesion["usuario_id"],
                        nueva,
                        rol_llamador=sesion["rol"],
                        llamador_id=sesion["usuario_id"],
                    )
                    seguridad.registrar_evento(tx, sesion["usuario_id"], "cambiar_clave", "cambio propio")
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
        encabezado_marca(contexto="sidebar")
        etiqueta_rol = nombre_rol(rol)
        st.markdown(
            f'<div class="ot-usuario-sidebar"><span class="ot-usuario-sidebar__nombre">{html.escape(str(sesion["nombre"]))}</span>'
            f'<span class="ot-usuario-sidebar__rol">{etiqueta_rol}</span></div>',
            unsafe_allow_html=True,
        )

        if not vistas:
            st.warning("Tu usuario no tiene pantallas asignadas todavía.")
            if st.button("Cerrar sesión", use_container_width=True, icon=":material/logout:"):
                _cerrar_sesion()
                st.rerun()
            pie_pagina()
            return

        claves = [v["key"] for v in vistas]
        vista_guardada = st.session_state.get("vista_actual")
        if vista_guardada not in claves:
            vista_guardada = claves[0]
            st.session_state["vista_actual"] = vista_guardada

        # Navegación propia (botones + session_state, D-sidebar): el
        # ítem activo se pinta como píldora sólida (`type="primary"`,
        # estilizada en `assets/theme.css` vía la clase `key=` del
        # contenedor) con icono Material real (`icon=":material/...:"`,
        # soporte nativo de `st.button` desde Streamlit >=1.36 — no
        # depende de ningún font-face propio). Se probó primero
        # `st.radio` + CSS sobre `data-testid` estables, pero ese widget
        # no permite renderizar un icono real dentro de cada opción (solo
        # texto plano); esta ruta sí lo permite sin tocar `views/__init__.py`.
        with st.container(key="ot-sidebar-nav"):
            for vista in vistas:
                activa = vista["key"] == vista_guardada
                if st.button(
                    vista["label"],
                    key=f"nav_{vista['key']}",
                    icon=f":material/{ICONOS_VISTA.get(vista['key'], 'circle')}:",
                    type="primary" if activa else "tertiary",
                    use_container_width=True,
                ):
                    st.session_state["vista_actual"] = vista["key"]
                    st.rerun()
        seleccion = st.session_state["vista_actual"]

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        _indicador_conexion(storage)
        if st.button("Cerrar sesión", use_container_width=True, icon=":material/logout:"):
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
    # Permite que `core.ui.inyectar_identidad_visual()` vuelva a pintar el
    # bloque `<style>` una vez en ESTE rerun (el DOM anterior ya no
    # existe) sin duplicarlo dentro del mismo rerun (ver su docstring).
    reiniciar_identidad_visual_para_este_rerun()

    # Modo demo (continuación §2.d): aviso permanente "DATOS DE PRUEBA"
    # ANTES de enrutar a cualquier vista. No hace nada si DEMO!=1.
    render_aviso_datos_prueba()

    storage = _storage_singleton()

    try:
        hay_usuarios = _hay_usuarios(storage)
    except BaseDeDatosNoDisponibleError as exc:
        mensaje_error_amable(exc, contexto="abrir_base")  # detalle solo al log
        _vista_base_no_disponible()
        return

    if hay_usuarios:
        _autorreparar_config(storage)
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
