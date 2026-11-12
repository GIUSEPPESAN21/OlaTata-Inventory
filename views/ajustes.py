"""Vista: Ajustes (solo admin). Propiedad de A5 (SHELL/TEMA/AJUSTES).

Secciones (§6): negocio, usuarios, estado de sincronización, respaldo,
verificar integridad, cierre de mes. Cada acción sensible revalida el
permiso con `core.permissions.requerir` (no basta con que el menú ya
esté filtrado por rol, §10) y cualquier `PermisoDenegadoError` se muestra
como un error amable, nunca como una traza de Python.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import streamlit as st

from core import auth, schema
from core.excel_safe import TextoInvalidoError, excel_safe
from core.permissions import PermisoDenegadoError, requerir
from core.timeutil import now_utc, parse_iso_utc, to_iso_utc
from core.ui import (
    chip_estado,
    confirmacion_coincide,
    encabezado_pagina,
    estado_vacio,
    formatear_fecha_hora_local,
    generar_password_temporal,
    mensaje_error_amable,
    resumen_estado_sync,
    validar_password,
)
from views import ViewContext

CLAVE_NEGOCIO_NOMBRE = "negocio_nombre"
CLAVE_NEGOCIO_WHATSAPP = "negocio_whatsapp"
CLAVE_NEGOCIO_MENSAJE_RECIBO = "negocio_mensaje_recibo"
CLAVE_NEGOCIO_CATEGORIAS = "negocio_categorias"
CLAVE_NEGOCIO_METODOS_PAGO = "negocio_metodos_pago_activos"
CLAVE_SESION_MINUTOS = "sesion_minutos"
# Clave distinta que `views/vender.py:255` lee para el enlace de
# WhatsApp del recibo (ver docs/CONTRATOS.md, sección "Claves de
# CONFIG" -> "Hallazgo"). Ajustes ahora escribe AMBAS claves al
# guardar el formulario de negocio, para que cambiar el WhatsApp desde
# aquí sí se refleje en el recibo sin tener que tocar `views/vender.py`
# (archivo que no es de A5).
CLAVE_TELEFONO_WHATSAPP_RECIBO = "telefono_whatsapp"
_SEP = "|"


def render(ctx: ViewContext) -> None:
    try:
        requerir(ctx.usuario.rol, "configurar_negocio")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para ver Ajustes: {exc}")
        return

    encabezado_pagina("Ajustes", "Negocio, usuarios, sincronización y respaldo.")
    tabs = st.tabs(
        ["Negocio", "Usuarios", "Sincronización", "Respaldo", "Integridad", "Cierre de mes"]
    )
    with tabs[0]:
        _tab_negocio(ctx)
    with tabs[1]:
        _tab_usuarios(ctx)
    with tabs[2]:
        _tab_sincronizacion(ctx)
    with tabs[3]:
        _tab_respaldo(ctx)
    with tabs[4]:
        _tab_integridad(ctx)
    with tabs[5]:
        _tab_cierre_mes(ctx)


# ------------------------------------------------------------- negocio
def _tab_negocio(ctx: ViewContext) -> None:
    storage = ctx.storage
    nombre_actual = storage.get_config(CLAVE_NEGOCIO_NOMBRE, "Ola Tata") or "Ola Tata"
    # Si `negocio_whatsapp` todavía no se ha guardado nunca desde este
    # formulario (instalación nueva sembrada solo por scripts/seed_db.py),
    # usa `telefono_whatsapp` como valor por defecto para no mostrar el
    # campo vacío cuando en realidad sí hay un número configurado.
    whatsapp_actual = (
        storage.get_config(CLAVE_NEGOCIO_WHATSAPP)
        or storage.get_config(CLAVE_TELEFONO_WHATSAPP_RECIBO)
        or ""
    )
    mensaje_actual = storage.get_config(CLAVE_NEGOCIO_MENSAJE_RECIBO, "") or ""
    categorias_actual = storage.get_config(CLAVE_NEGOCIO_CATEGORIAS, "") or ""
    metodos_defecto = _SEP.join(sorted(schema.METODOS_PAGO))
    metodos_actual = storage.get_config(CLAVE_NEGOCIO_METODOS_PAGO, metodos_defecto) or metodos_defecto
    minutos_actual = storage.get_config(CLAVE_SESION_MINUTOS, str(auth.SESION_MINUTOS_DEFAULT))

    metodos_seleccionados = [m for m in metodos_actual.split(_SEP) if m in schema.METODOS_PAGO]

    with st.form("formulario_negocio"):
        nombre = st.text_input("Nombre del negocio", value=nombre_actual)
        whatsapp = st.text_input("Teléfono WhatsApp", value=whatsapp_actual)
        mensaje = st.text_area("Mensaje de recibo", value=mensaje_actual, height=100)
        categorias_texto = st.text_area(
            "Categorías de producto (una por línea)",
            value=categorias_actual.replace(_SEP, "\n"),
            height=100,
        )
        metodos = st.multiselect(
            "Métodos de pago activos",
            options=sorted(schema.METODOS_PAGO),
            default=metodos_seleccionados,
        )
        try:
            minutos_valor_inicial = int(minutos_actual)
        except (TypeError, ValueError):
            minutos_valor_inicial = auth.SESION_MINUTOS_DEFAULT
        minutos = st.number_input(
            "Minutos de inactividad antes de cerrar sesión",
            min_value=5,
            max_value=24 * 60,
            value=minutos_valor_inicial,
            step=5,
        )
        guardar = st.form_submit_button("Guardar", use_container_width=True)

    if not guardar:
        return

    try:
        nombre_limpio = excel_safe(nombre, field_name="nombre del negocio")
        whatsapp_limpio = excel_safe(whatsapp, field_name="teléfono WhatsApp")
        mensaje_limpio = excel_safe(mensaje, max_length=4000, field_name="mensaje de recibo")
        categorias_lista = [
            excel_safe(c, field_name="categoría") for c in categorias_texto.splitlines() if c.strip()
        ]
    except TextoInvalidoError as exc:
        st.error(str(exc))
        return

    try:
        with storage.transaction() as tx:
            tx.set_config(CLAVE_NEGOCIO_NOMBRE, nombre_limpio)
            tx.set_config(CLAVE_NEGOCIO_WHATSAPP, whatsapp_limpio)
            # Corrige el hallazgo documentado en docs/CONTRATOS.md: el
            # recibo de venta (views/vender.py) lee `telefono_whatsapp`,
            # no `negocio_whatsapp`. Se escriben ambas claves para que
            # el enlace de WhatsApp del recibo quede sincronizado con lo
            # que un admin configura aquí.
            tx.set_config(CLAVE_TELEFONO_WHATSAPP_RECIBO, whatsapp_limpio)
            tx.set_config(CLAVE_NEGOCIO_MENSAJE_RECIBO, mensaje_limpio)
            tx.set_config(CLAVE_NEGOCIO_CATEGORIAS, _SEP.join(categorias_lista))
            tx.set_config(CLAVE_NEGOCIO_METODOS_PAGO, _SEP.join(metodos))
            tx.set_config(CLAVE_SESION_MINUTOS, str(int(minutos)))
    except Exception as exc:  # nunca una traza de Python visible (§6)
        mensaje, _codigo = mensaje_error_amable(exc, contexto="ajustes_negocio")
        st.error(mensaje)
    else:
        st.success("Datos del negocio guardados.")
        ctx.rerun()


# ------------------------------------------------------------- usuarios
def _tab_usuarios(ctx: ViewContext) -> None:
    storage = ctx.storage
    st.subheader("Crear usuario")
    if "ajustes_clave_sugerida" not in st.session_state:
        st.session_state["ajustes_clave_sugerida"] = generar_password_temporal()

    with st.form("formulario_crear_usuario"):
        nombre = st.text_input("Nombre completo")
        usuario_nuevo = st.text_input("Usuario")
        rol = st.selectbox(
            "Rol",
            options=["vendedor", "admin"],
            format_func=lambda r: "Administrador" if r == "admin" else "Vendedor",
        )
        usar_generada = st.checkbox("Usar clave temporal generada", value=True)
        if usar_generada:
            st.code(st.session_state["ajustes_clave_sugerida"])
            clave = st.session_state["ajustes_clave_sugerida"]
        else:
            clave = st.text_input("Clave temporal", type="password")
        crear = st.form_submit_button("Crear usuario", use_container_width=True)

    if crear:
        _crear_usuario(ctx, nombre, usuario_nuevo, rol, clave)

    st.divider()
    st.subheader("Usuarios existentes")
    df = storage.read_sheet(schema.USUARIOS)
    if df.empty:
        estado_vacio("Todavía no hay usuarios creados.")
        return
    for _, fila in df.iterrows():
        _fila_usuario(ctx, fila)


def _crear_usuario(ctx: ViewContext, nombre: str, usuario_nuevo: str, rol: str, clave: str) -> None:
    try:
        requerir(ctx.usuario.rol, "gestionar_usuarios")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    errores = []
    if not nombre.strip():
        errores.append("Escribe el nombre.")
    if not usuario_nuevo.strip():
        errores.append("Escribe el usuario.")
    error_password = validar_password(clave or "")
    if error_password:
        errores.append(error_password)
    if errores:
        for err in errores:
            st.error(err)
        return

    try:
        with ctx.storage.transaction() as tx:
            auth.crear_usuario(
                tx,
                nombre=excel_safe(nombre.strip(), field_name="nombre"),
                usuario=usuario_nuevo.strip(),
                password_plano=clave,
                rol=rol,
                must_change_password=True,
                rol_llamador=ctx.usuario.rol,
            )
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:  # nunca una traza de Python visible (§6)
        mensaje, _codigo = mensaje_error_amable(exc, contexto="crear_usuario")
        st.error(mensaje)
    else:
        st.session_state.pop("ajustes_clave_sugerida", None)
        st.success(f"Usuario '{usuario_nuevo}' creado con clave temporal. Debe cambiarla al ingresar.")
        ctx.rerun()


def _fila_usuario(ctx: ViewContext, fila) -> None:
    storage = ctx.storage
    activo = bool(fila["activo"])
    col1, col2, col3 = st.columns([3, 2, 3])
    with col1:
        etiqueta_rol = "Administrador" if fila["rol"] == "admin" else "Vendedor"
        st.write(f"**{fila['nombre']}** ({fila['usuario']}) — {etiqueta_rol}")
    with col2:
        if activo:
            st.markdown(chip_estado("Activo", "exito"), unsafe_allow_html=True)
        else:
            st.markdown(chip_estado("Inactivo", "error", icono="pause_circle"), unsafe_allow_html=True)
    with col3:
        clave_mostrar_confirmacion = f"ajustes_confirmar_{fila['id']}"
        accion = "Desactivar" if activo else "Activar"
        if st.button(accion, key=f"ajustes_btn_{fila['id']}", use_container_width=True):
            st.session_state[clave_mostrar_confirmacion] = True

        if st.session_state.get(clave_mostrar_confirmacion):
            texto = st.text_input(
                f"Escribe '{fila['usuario']}' para confirmar",
                key=f"ajustes_input_{fila['id']}",
            )
            if st.button("Confirmar", key=f"ajustes_confirmar_btn_{fila['id']}"):
                if not confirmacion_coincide(str(fila["usuario"]), texto):
                    st.error("El texto no coincide con el usuario.")
                else:
                    _alternar_activo(ctx, storage, fila, activo)


def _alternar_activo(ctx: ViewContext, storage, fila, activo_actual: bool) -> None:
    try:
        requerir(ctx.usuario.rol, "gestionar_usuarios")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return
    try:
        with storage.transaction() as tx:
            df = tx.read_sheet(schema.USUARIOS)
            coincide = df["id"] == fila["id"]
            df.loc[coincide, "activo"] = not activo_actual
            df.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
            tx.write_sheet(schema.USUARIOS, df)
    except Exception as exc:  # nunca una traza de Python visible (§6)
        mensaje, _codigo = mensaje_error_amable(exc, contexto="alternar_activo_usuario")
        st.error(mensaje)
    else:
        st.session_state.pop(f"ajustes_confirmar_{fila['id']}", None)
        ctx.rerun()


# -------------------------------------------------------- sincronización
def _tab_sincronizacion(ctx: ViewContext) -> None:
    try:
        requerir(ctx.usuario.rol, "resolver_conflicto_sync")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para ver esto: {exc}")
        return

    status = ctx.storage.sync_status()
    resumen = resumen_estado_sync(status)
    mostrar = {"error": st.error, "alerta": st.warning, "exito": st.success}.get(resumen["categoria"], st.info)
    mostrar(resumen["texto"])

    ultimo_sync = getattr(status, "ultimo_sync_utc", None)
    if ultimo_sync:
        try:
            st.caption(f"Último sincronizado: {formatear_fecha_hora_local(parse_iso_utc(ultimo_sync))}")
        except Exception:
            pass
    ultimo_error = getattr(status, "ultimo_error", None)
    if ultimo_error:
        st.caption(f"Último error técnico: {ultimo_error}")

    if getattr(status, "en_conflicto", False):
        st.warning(
            "Hay una versión en conflicto entre lo guardado en este equipo "
            "(local) y lo que hay en GitHub (remota)."
        )
        st.info(
            "**Pendiente documentado (M1):** `core.storage` todavía no "
            "expone una función para elegir y aplicar una de las dos "
            "versiones byte a byte — aquí solo se deja constancia de cuál "
            "se prefiere. Pídele al equipo técnico completar la "
            "resolución manualmente mientras esa función no exista."
        )
        eleccion = st.radio("¿Qué versión prefieres conservar?", ["Local (este equipo)", "Remota (GitHub)"])
        if st.button("Dejar constancia de la elección", use_container_width=True):
            st.success(f"Elección registrada: {eleccion}. Avisa al soporte técnico para completarla.")


# -------------------------------------------------------------- respaldo
def _tab_respaldo(ctx: ViewContext) -> None:
    try:
        requerir(ctx.usuario.rol, "descargar_respaldo")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    local_path = getattr(ctx.storage, "local_path", None)
    if local_path is None or not Path(local_path).exists():
        estado_vacio(
            "Todavía no hay datos guardados para respaldar.",
            "Vuelve cuando haya al menos un producto o una venta registrada.",
        )
        return

    try:
        contenido = Path(local_path).read_bytes()
    except OSError as exc:
        mensaje, _codigo = mensaje_error_amable(exc, contexto="descargar_respaldo")
        st.error(mensaje)
        return

    st.download_button(
        "Descargar respaldo (.xlsx)",
        data=contenido,
        file_name=Path(local_path).name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ------------------------------------------------------------ integridad
def _tab_integridad(ctx: ViewContext) -> None:
    try:
        requerir(ctx.usuario.rol, "verificar_integridad")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    verificar = _funcion_opcional("core.inventory", "verificar_integridad")
    if verificar is None:
        estado_vacio("Verificar integridad estará disponible cuando Inventario esté integrado.")
        return

    if st.button("Verificar integridad del inventario", use_container_width=True):
        try:
            resultado = verificar(ctx.storage)
        except Exception as exc:  # nunca una traza de Python visible (§6)
            mensaje, _codigo = mensaje_error_amable(exc, contexto="verificar_integridad")
            st.error(mensaje)
        else:
            st.success(str(resultado))


# ----------------------------------------------------------- cierre mes
def _tab_cierre_mes(ctx: ViewContext) -> None:
    try:
        requerir(ctx.usuario.rol, "cerrar_mes")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    cerrar = _funcion_opcional("core.monthly_close", "cerrar_mes")
    if cerrar is None:
        estado_vacio("El cierre de mes estará disponible cuando ese módulo esté integrado.")
        return

    st.warning(
        "Cerrar el mes archiva y vacía las hojas de ventas, pagos, "
        "devoluciones, movimientos y cuadre de caja. Esta acción no se "
        "puede deshacer."
    )
    confirmacion = st.text_input("Escribe CERRAR MES para confirmar")
    confirmado = confirmacion_coincide("CERRAR MES", confirmacion)
    if st.button("Cerrar mes", use_container_width=True, disabled=not confirmado):
        try:
            resultado = cerrar(ctx.storage)
        except Exception as exc:  # nunca una traza de Python visible (§6)
            mensaje, _codigo = mensaje_error_amable(exc, contexto="cerrar_mes")
            st.error(mensaje)
        else:
            st.success(str(resultado))


def _funcion_opcional(nombre_modulo: str, nombre_funcion: str):
    """Importa una función de un módulo de dominio que todavía puede no
    existir en esta rama (A1-A4 en progreso). Devuelve `None` si el
    módulo o la función no existen todavía — nunca truena."""
    try:
        modulo = importlib.import_module(nombre_modulo)
    except ImportError:
        return None
    return getattr(modulo, nombre_funcion, None)
