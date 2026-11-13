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

import pandas as pd
import streamlit as st

from core import auth, inicio_produccion, schema, seguridad
from core.excel_safe import TextoInvalidoError, excel_safe
from core.permissions import MAESTRO, PermisoDenegadoError, nombre_rol, requerir, tiene_capacidad
from core.sincronizacion import (
    OPCION_CONSERVAR_LOCAL,
    OPCION_USAR_NUBE,
    estado_conexion,
    resolver_conflicto,
    sincronizar_ahora,
)
from core.timeutil import parse_iso_utc
from core.ui import (
    card,
    chip_estado,
    confirmacion_coincide,
    encabezado_pagina,
    estado_vacio,
    formatear_fecha_hora_local,
    generar_password_temporal,
    guia,
    md_seguro,
    mensaje_error_amable,
    resumen_estado_sync,
    tabla_amigable,
    titulo_seccion,
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

    encabezado_pagina("Ajustes", "Negocio, usuarios, sincronización y respaldo.", icono="settings")
    guia("ajustes")
    es_maestro = tiene_capacidad(ctx.usuario.rol, "datos_prueba")
    nombres_tabs = ["Negocio", "Usuarios", "Sincronización", "Respaldo", "Integridad", "Cierre de mes"]
    if es_maestro:
        nombres_tabs.append("Datos de prueba")
    tabs = st.tabs(nombres_tabs)
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
    if es_maestro:
        with tabs[6]:
            _tab_datos_prueba(ctx)


# ------------------------------------------------------------- negocio
def _tab_negocio(ctx: ViewContext) -> None:
    guia("ajustes_negocio")
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

    with card(acento="superior"):
        titulo_seccion("Datos del negocio")
        with st.form("formulario_negocio"):
            nombre = st.text_input("Nombre del negocio", value=nombre_actual, icon=":material/storefront:")
            whatsapp = st.text_input("Teléfono WhatsApp", value=whatsapp_actual, icon=":material/call:")
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
            guardar = st.form_submit_button("Guardar", use_container_width=True, type="primary", icon=":material/save:")

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
    guia("ajustes_usuarios")
    storage = ctx.storage
    if "ajustes_clave_sugerida" not in st.session_state:
        st.session_state["ajustes_clave_sugerida"] = generar_password_temporal()

    with card(acento="superior"):
        titulo_seccion("Crear usuario")
        with st.form("formulario_crear_usuario"):
            nombre = st.text_input("Nombre completo", icon=":material/badge:")
            usuario_nuevo = st.text_input("Usuario", icon=":material/person:")
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
                clave = st.text_input("Clave temporal", type="password", icon=":material/lock:")
            crear = st.form_submit_button("Crear usuario", use_container_width=True, type="primary", icon=":material/person_add:")

    if crear:
        _crear_usuario(ctx, nombre, usuario_nuevo, rol, clave)

    with card(acento="izquierdo"):
        titulo_seccion("Usuarios existentes")
        df = storage.read_sheet(schema.USUARIOS)
        if df.empty:
            estado_vacio("Todavía no hay usuarios creados.", icono="group")
        else:
            for _, fila in df.iterrows():
                _fila_usuario(ctx, fila)
    _registro_seguridad(ctx)


def _crear_usuario(ctx: ViewContext, nombre: str, usuario_nuevo: str, rol: str, clave: str) -> None:
    try:
        requerir(ctx.usuario.rol, "gestionar_usuarios")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    errores = []
    if not nombre.strip():
        errores.append("Escribe el nombre.")
    error_usuario = seguridad.validar_nombre_usuario(usuario_nuevo)
    if error_usuario:
        errores.append(error_usuario)
    error_password = validar_password(clave or "", usuario=usuario_nuevo.strip(), nombre=nombre.strip())
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
                nombre=excel_safe(nombre.strip(), field_name="nombre"),
                usuario=usuario_nuevo.strip(),
                password_plano=clave,
                rol=rol,
                must_change_password=True,
                rol_llamador=ctx.usuario.rol,
            )
            seguridad.registrar_evento(
                tx, ctx.usuario.id, "crear_usuario", f"usuario={usuario_nuevo.strip()} rol={rol} id={nuevo_id}"
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
        st.markdown(f"**{md_seguro(fila['nombre'])}** ({md_seguro(fila['usuario'])}) — {nombre_rol(fila['rol'])}")
    with col2:
        if activo:
            st.markdown(chip_estado("Activo", "exito"), unsafe_allow_html=True)
        else:
            st.markdown(chip_estado("Inactivo", "error", icono="pause_circle"), unsafe_allow_html=True)
    with col3:
        es_cuenta_maestra = fila["rol"] == MAESTRO
        if tiene_capacidad(ctx.usuario.rol, "editar_usuarios"):
            _popover_editar_usuario(ctx, fila)
        if es_cuenta_maestra:
            st.caption("Cuenta maestra: no se puede desactivar.")
            return
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

        if activo and fila["id"] != ctx.usuario.id:
            with st.popover("Restablecer clave", icon=":material/lock_reset:", use_container_width=True):
                st.caption(
                    "Genera una clave temporal nueva, cierra todas sus sesiones abiertas y le pedirá "
                    "cambiarla al ingresar. Entrégala en persona."
                )
                if st.button("Generar clave temporal", key=f"ajustes_reset_{fila['id']}", type="primary"):
                    try:
                        with storage.transaction() as tx:
                            clave = seguridad.restablecer_password(tx, ctx.usuario.rol, ctx.usuario.id, fila["id"])
                    except (PermisoDenegadoError, ValueError) as exc:
                        st.error(str(exc))
                    except Exception as exc:  # nunca una traza visible
                        mensaje, _codigo = mensaje_error_amable(exc, contexto="restablecer_clave")
                        st.error(mensaje)
                    else:
                        st.success("Clave restablecida. Cópiala ahora: no se volverá a mostrar.")
                        st.code(clave, language=None)


def _popover_editar_usuario(ctx: ViewContext, fila) -> None:
    """Solo el maestro: cambiar nombre, usuario y rol de una cuenta."""
    es_cuenta_maestra = fila["rol"] == MAESTRO
    with st.popover("Editar", icon=":material/edit:", use_container_width=True):
        with st.form(f"ajustes_editar_{fila['id']}"):
            nombre = st.text_input("Nombre completo", value=str(fila["nombre"]))
            usuario = st.text_input("Usuario", value=str(fila["usuario"]))
            if es_cuenta_maestra:
                st.caption("Rol: Maestro (no se cambia).")
                rol = None
            else:
                opciones = ["vendedor", "admin"]
                rol = st.selectbox(
                    "Rol", opciones, index=opciones.index(fila["rol"]) if fila["rol"] in opciones else 0,
                    format_func=nombre_rol,
                )
            guardar = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)
        if guardar:
            try:
                with ctx.storage.transaction() as tx:
                    cambios = seguridad.editar_usuario(
                        tx, ctx.usuario.rol, ctx.usuario.id, fila["id"], nombre=nombre, usuario=usuario, rol=rol
                    )
            except (PermisoDenegadoError, ValueError) as exc:
                st.error(str(exc))
            except Exception as exc:  # nunca una traza visible
                mensaje, _codigo = mensaje_error_amable(exc, contexto="editar_usuario")
                st.error(mensaje)
            else:
                if not cambios:
                    st.info("No había cambios.")
                elif fila["id"] == ctx.usuario.id and "usuario" in cambios:
                    st.success("Guardado. Como cambiaste tu usuario, vuelve a ingresar con el nuevo.")
                    ctx.rerun()
                else:
                    st.success("Cambios guardados." + (" Sus sesiones abiertas se cerraron." if {"usuario", "rol"} & set(cambios) else ""))
                    ctx.rerun()


def _tab_datos_prueba(ctx: ViewContext) -> None:
    """Solo el maestro: crear o eliminar los datos de prueba."""
    guia("ajustes_datos_prueba")
    from core import datos_prueba

    with card(acento="superior"):
        titulo_seccion("Datos de prueba")
        if datos_prueba.hay_datos_prueba(ctx.storage):
            st.markdown(chip_estado("Hay datos de prueba en la base", "alerta", icono="science"), unsafe_allow_html=True)
            st.caption(
                "Usuarios prueba.admin y prueba.vendedor, los 3 productos «[PRUEBA] …» y sus ventas. "
                "Elimínalos antes de empezar a vender de verdad: afectan las cifras de Análisis."
            )
            confirmar = st.text_input("Escribe ELIMINAR para confirmar", key="ajustes_prueba_confirmar")
            if st.button("Eliminar datos de prueba", icon=":material/delete:", use_container_width=True):
                if not confirmacion_coincide("ELIMINAR", confirmar):
                    st.error("Escribe ELIMINAR para confirmar.")
                    return
                try:
                    quitadas = datos_prueba.eliminar_datos_prueba(ctx.storage, ctx.usuario.rol, ctx.usuario.id)
                except (PermisoDenegadoError, ValueError) as exc:
                    st.error(str(exc))
                except Exception as exc:
                    mensaje, _codigo = mensaje_error_amable(exc, contexto="eliminar_datos_prueba")
                    st.error(mensaje)
                else:
                    st.session_state.pop("ajustes_prueba_claves", None)
                    st.success(f"Datos de prueba eliminados ({sum(quitadas.values())} registros).")
                    ctx.rerun()
        elif inicio_produccion.produccion_iniciada(ctx.storage):
            st.caption("La operación real ya empezó: no se crean más datos de prueba.")
        else:
            st.caption(
                "Crea dos usuarios de prueba (administrador y vendedor), 3 productos de prueba (bolso, cartera y "
                "billetera) con stock y una venta simulada, para probar la app sin tocar datos reales."
            )
            if st.button("Crear datos de prueba", type="primary", icon=":material/science:", use_container_width=True):
                try:
                    resultado = datos_prueba.crear_datos_prueba(ctx.storage, ctx.usuario.rol, ctx.usuario.id)
                except (PermisoDenegadoError, ValueError) as exc:
                    st.error(str(exc))
                except Exception as exc:
                    mensaje, _codigo = mensaje_error_amable(exc, contexto="crear_datos_prueba")
                    st.error(mensaje)
                else:
                    st.session_state["ajustes_prueba_claves"] = resultado
                    ctx.rerun()

        resultado = st.session_state.get("ajustes_prueba_claves")
        if resultado:
            st.success(
                f"Listo: productos {', '.join(resultado.get('productos', [resultado['producto_id']]))} y "
                f"venta {resultado['venta_numero']} creados. "
                "Anota estas claves AHORA: no se volverán a mostrar."
            )
            for usuario, clave in resultado["usuarios"].items():
                st.markdown(f"**{md_seguro(usuario)}**")
                st.code(clave, language=None)

    _seccion_inicio_produccion(ctx)


def _seccion_inicio_produccion(ctx: ViewContext) -> None:
    """Limpieza ÚNICA para empezar con el inventario real (solo maestro)."""
    with card(acento="izquierdo", key="ot-card-inicio-produccion"):
        titulo_seccion("Empezar con el inventario real")
        fecha = inicio_produccion.produccion_iniciada(ctx.storage)
        if fecha:
            try:
                cuando = formatear_fecha_hora_local(parse_iso_utc(fecha))
            except Exception:
                cuando = fecha
            st.markdown(chip_estado(f"Operación real iniciada el {cuando}", "exito", icono="verified"),
                        unsafe_allow_html=True)
            st.caption("Esta limpieza ya se hizo y no se puede repetir.")
            return
        st.caption(
            "Cuando terminen de probar: deja la app vacía para cargar el inventario real. "
            "Solo se puede hacer UNA vez."
        )
        resumen = inicio_produccion.resumen_a_borrar(ctx.storage)
        etiquetas = {
            "productos": "Productos", "stock": "Existencias", "movimientos": "Movimientos de inventario",
            "ventas": "Ventas", "venta_items": "Productos vendidos", "pagos": "Pagos", "devoluciones": "Devoluciones",
            "devolucion_items": "Productos devueltos", "proveedores": "Proveedores", "cuadre_caja": "Cuadres de caja",
            "usuarios de prueba": "Usuarios de prueba",
        }
        borrar = [f"{etiquetas.get(h, h)}: {n}" for h, n in resumen.items() if n]
        st.markdown("**Se borra:** " + (" · ".join(borrar) if borrar else "nada (la base ya está vacía)"))
        st.markdown("**Se conserva:** usuarios reales, configuración del negocio y registro de seguridad.")
        st.warning(
            "Antes, descarga un respaldo (pestaña Respaldo). Bota también las etiquetas y recibos de prueba "
            "que hayas impreso, para no confundirlos con los reales."
        )
        frase = st.text_input(
            f'Escribe "{inicio_produccion.FRASE_CONFIRMACION}" para confirmar', key="ajustes_inicio_frase"
        )
        if st.button("Empezar con el inventario real", type="primary", icon=":material/rocket_launch:",
                     use_container_width=True):
            try:
                borradas = inicio_produccion.iniciar_produccion(ctx.storage, ctx.usuario.rol, ctx.usuario.id, frase)
            except (PermisoDenegadoError, ValueError) as exc:
                st.error(str(exc))
            except Exception as exc:  # nunca una traza visible
                mensaje, _codigo = mensaje_error_amable(exc, contexto="iniciar_produccion")
                st.error(mensaje)
            else:
                st.session_state.pop("ajustes_prueba_claves", None)
                st.success(f"Listo: la app quedó limpia ({sum(borradas.values())} registros borrados). ¡A vender!")
                ctx.rerun()


def _alternar_activo(ctx: ViewContext, storage, fila, activo_actual: bool) -> None:
    try:
        with storage.transaction() as tx:
            seguridad.cambiar_estado_usuario(
                tx, ctx.usuario.rol, ctx.usuario.id, fila["id"], activo=not activo_actual
            )
    except (PermisoDenegadoError, ValueError) as exc:
        st.error(str(exc))
    except Exception as exc:  # nunca una traza de Python visible (§6)
        mensaje, _codigo = mensaje_error_amable(exc, contexto="alternar_activo_usuario")
        st.error(mensaje)
    else:
        st.session_state.pop(f"ajustes_confirmar_{fila['id']}", None)
        ctx.rerun()


def _registro_seguridad(ctx: ViewContext) -> None:
    """Últimos eventos de `auditoria`: quién ingresó, cambió claves o
    gestionó usuarios, y cuándo (hora de Bogotá)."""
    try:
        eventos = seguridad.eventos_recientes(ctx.storage, ctx.usuario.rol, limite=50)
    except PermisoDenegadoError:
        return
    with card(acento="izquierdo"):
        titulo_seccion("Registro de seguridad")
        st.caption("Últimos 50 eventos: ingresos, cambios de clave y cambios en usuarios.")
        if eventos.empty:
            estado_vacio("Todavía no hay eventos registrados.", icono="shield")
            return
        usuarios = ctx.storage.read_sheet(schema.USUARIOS)
        nombres = dict(zip(usuarios["id"].astype(str), usuarios["usuario"].astype(str)))
        acciones = {
            "ingreso": "Ingreso",
            "cambiar_clave": "Cambio de clave",
            "restablecer_clave": "Clave restablecida",
            "crear_usuario": "Usuario creado",
            "crear_admin": "Administrador creado",
            "activar_usuario": "Usuario activado",
            "desactivar_usuario": "Usuario desactivado",
            "cerrar_mes": "Cierre de mes",
        }
        tabla = pd.DataFrame(
            {
                "fecha_hora_utc": eventos["ts"],
                "usuario": eventos["usuario"].astype(str).map(lambda u: nombres.get(u, u)),
                "accion": eventos["accion"].astype(str).map(lambda a: acciones.get(a, a)),
                "detalle": eventos["detalle"].fillna(""),
            }
        )
        st.dataframe(tabla_amigable(tabla), use_container_width=True, hide_index=True)


# -------------------------------------------------------- sincronización
def _tab_sincronizacion(ctx: ViewContext) -> None:
    guia("ajustes_sincronizacion")
    try:
        requerir(ctx.usuario.rol, "resolver_conflicto_sync")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para ver esto: {exc}")
        return

    with card(acento="superior"):
        titulo_seccion("Estado de sincronización")
        status = ctx.storage.sync_status()
        if getattr(ctx.storage, "sync_enabled", False):
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

        conexion = estado_conexion(ctx.storage)
        if conexion.modo == "nube":
            st.markdown(
                chip_estado(f"Conectado a GitHub · {conexion.repositorio}", "exito", icono="cloud_done"),
                unsafe_allow_html=True,
            )
            if conexion.sha_remoto:
                st.caption(f"Versión en la nube: {conexion.sha_remoto[:7]}")
        else:
            st.markdown(
                chip_estado("Modo local: los datos se guardan solo en este equipo", "alerta", icono="computer"),
                unsafe_allow_html=True,
            )
            st.caption(
                "Para activar la base en la nube, configura GITHUB_TOKEN, GITHUB_REPO y "
                "GITHUB_REPO_ARCHIVE en los Secrets de la app (ver DEPLOY.md)."
            )

        if conexion.modo == "nube" and not getattr(status, "en_conflicto", False):
            if st.button("Sincronizar ahora", use_container_width=True, icon=":material/sync:"):
                try:
                    nuevo_estado = sincronizar_ahora(ctx.storage, ctx.usuario.rol)
                except Exception as exc:  # nunca una traza visible
                    mensaje, _codigo = mensaje_error_amable(exc, contexto="sincronizar_ahora")
                    st.error(mensaje)
                else:
                    if nuevo_estado.pendientes == 0 and not nuevo_estado.en_conflicto:
                        st.success("Listo: la base en la nube está al día.")
                    else:
                        st.warning(resumen_estado_sync(nuevo_estado)["texto"])

        if getattr(status, "en_conflicto", False):
            st.warning(
                "La base en GitHub cambió por fuera de esta app (por ejemplo, alguien "
                "restauró una versión). Elige qué versión conservar. Ninguna opción "
                "borra datos: la versión de GitHub queda en su historial y la copia "
                "de este equipo se guarda como respaldo."
            )
            eleccion = st.radio(
                "¿Qué versión conservar?",
                ["Usar la versión de la nube (GitHub)", "Conservar la versión de este equipo"],
                key="ajustes_conflicto_eleccion",
            )
            confirmar = st.text_input('Escribe "CONFIRMAR" para aplicar', key="ajustes_conflicto_confirmar")
            if st.button("Aplicar elección", type="primary", use_container_width=True, icon=":material/fact_check:"):
                if not confirmacion_coincide("CONFIRMAR", confirmar):
                    st.error('Escribe "CONFIRMAR" para continuar.')
                else:
                    opcion = OPCION_USAR_NUBE if eleccion.startswith("Usar") else OPCION_CONSERVAR_LOCAL
                    try:
                        resolver_conflicto(ctx.storage, ctx.usuario.rol, opcion)
                    except Exception as exc:
                        mensaje, _codigo = mensaje_error_amable(exc, contexto="resolver_conflicto")
                        st.error(mensaje)
                    else:
                        st.success("Conflicto resuelto.")
                        ctx.rerun()


# -------------------------------------------------------------- respaldo
def _tab_respaldo(ctx: ViewContext) -> None:
    guia("ajustes_respaldo")
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
            icono="backup",
        )
        return

    try:
        contenido = Path(local_path).read_bytes()
    except OSError as exc:
        mensaje, _codigo = mensaje_error_amable(exc, contexto="descargar_respaldo")
        st.error(mensaje)
        return

    with card(acento="superior"):
        titulo_seccion("Respaldo")
        st.download_button(
            "Descargar respaldo (.xlsx)",
            data=contenido,
            file_name=Path(local_path).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            icon=":material/backup:",
        )


# ------------------------------------------------------------ integridad
def _tab_integridad(ctx: ViewContext) -> None:
    guia("ajustes_integridad")
    try:
        requerir(ctx.usuario.rol, "verificar_integridad")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    verificar = _funcion_opcional("core.inventory", "verificar_integridad")
    if verificar is None:
        estado_vacio("Verificar integridad estará disponible cuando Inventario esté integrado.", icono="fact_check")
        return

    with card(acento="superior"):
        titulo_seccion("Integridad del inventario")
        if st.button("Verificar integridad del inventario", use_container_width=True, icon=":material/fact_check:"):
            try:
                resultado = verificar(ctx.storage)
            except Exception as exc:  # nunca una traza de Python visible (§6)
                mensaje, _codigo = mensaje_error_amable(exc, contexto="verificar_integridad")
                st.error(mensaje)
            else:
                st.success(str(resultado))


# ----------------------------------------------------------- cierre mes
def _tab_cierre_mes(ctx: ViewContext) -> None:
    guia("ajustes_cierre")
    try:
        requerir(ctx.usuario.rol, "cerrar_mes")
    except PermisoDenegadoError as exc:
        st.error(f"No tienes permiso para esto: {exc}")
        return

    cerrar = _funcion_opcional("core.monthly_close", "cerrar_mes")
    if cerrar is None:
        estado_vacio("El cierre de mes estará disponible cuando ese módulo esté integrado.", icono="event_busy")
        return

    with card(acento="superior", key="ot-card-peligro"):
        titulo_seccion("Zona de peligro — cierre de mes")
        st.warning(
            "Cerrar el mes archiva y vacía las hojas de ventas, pagos, "
            "devoluciones, movimientos y cuadre de caja. Esta acción no se "
            "puede deshacer."
        )
        confirmacion = st.text_input("Escribe CERRAR MES para confirmar")
        confirmado = confirmacion_coincide("CERRAR MES", confirmacion)
        if st.button(
            "Cerrar mes", use_container_width=True, disabled=not confirmado, icon=":material/lock:"
        ):
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
