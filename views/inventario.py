"""Vista: Inventario. Propiedad de A1 (INVENTARIO). Contrato: `render(ctx)`.

Pantalla admin-only (requiere la capacidad "gestionar_inventario", §6: el
vendedor nunca ve costos). Incluye: lista con filtros y búsqueda,
crear/editar producto, activar/desactivar, entrada de mercancía, conteo
físico, importación inicial desde Excel/CSV (con vista previa de errores)
y etiquetas con código de barras en PDF.
"""
from __future__ import annotations

import logging
import secrets

import pandas as pd
import streamlit as st

from core import costing, importer, inventory, labels_ot
from core.money import DineroInvalidoError, format_cop
from core.permissions import PermisoDenegadoError, requerir, tiene_capacidad
from core.schema import SEDE_PRINCIPAL
from core.ui import card, chip_estado, encabezado_pagina, estado_vacio, titulo_seccion
from views import ViewContext

logger = logging.getLogger(__name__)


def _mensaje_amigable(exc: Exception, contexto: str) -> str:
    """Error amable con código de incidente: el detalle va al log, nunca
    la traza al usuario (§6)."""
    codigo = secrets.token_hex(4)
    logger.exception("Incidente %s en %s", codigo, contexto)
    return (
        f"Ocurrió un problema inesperado ({contexto}). "
        f"Código de incidente: {codigo}. Intenta de nuevo o avisa al administrador."
    )


def render(ctx: ViewContext) -> None:
    usuario = ctx.usuario
    rol = getattr(usuario, "rol", None)

    # §10: la UI oculta el menú, pero la capacidad se revalida aquí también.
    if not tiene_capacidad(rol, "gestionar_inventario"):
        st.error("No tienes permiso para ver el inventario. Esta pantalla es solo para administradores.")
        return

    encabezado_pagina("Inventario", "Productos, mercancía y existencias", icono="inventory_2")

    tabs = st.tabs(
        ["Productos", "Entrada de mercancía", "Conteo físico", "Importar inventario", "Etiquetas", "Integridad"]
    )
    with tabs[0]:
        _tab_productos(ctx, rol)
    with tabs[1]:
        _tab_entrada(ctx, rol)
    with tabs[2]:
        _tab_conteo(ctx, rol)
    with tabs[3]:
        _tab_importar(ctx, rol)
    with tabs[4]:
        _tab_etiquetas(ctx, rol)
    with tabs[5]:
        _tab_integridad(ctx, rol)


# --------------------------------------------------------------- Productos
def _tab_productos(ctx: ViewContext, rol: str) -> None:
    try:
        productos = inventory.listar_productos(ctx.storage, rol)
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "listar productos"))
        return

    with card(acento="superior"):
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        with col1:
            busqueda = st.text_input("Buscar por nombre o código de barras", key="inv_busqueda", icon=":material/search:")
        with col2:
            categorias = sorted({c for c in productos["categoria"].astype(str) if c})
            categoria = st.selectbox("Categoría", options=["(todas)"] + categorias, key="inv_categoria")
        with col3:
            bajo_minimo = st.checkbox("Bajo mínimo", key="inv_bajo_minimo")
        with col4:
            sin_stock = st.checkbox("Sin stock", key="inv_sin_stock")

    try:
        filtrados = inventory.listar_productos(
            ctx.storage,
            rol,
            categoria=None if categoria == "(todas)" else categoria,
            bajo_minimo=bajo_minimo,
            sin_stock=sin_stock,
            busqueda=busqueda or None,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "filtrar productos"))
        return

    if filtrados.empty:
        estado_vacio(
            "No hay productos que coincidan con estos filtros.",
            "Crea uno nuevo con el formulario de abajo.",
            icono="search_off",
        )
    else:
        mostrar = filtrados.copy()
        mostrar["costo"] = mostrar["costo"].apply(lambda v: format_cop(int(v)) if pd.notna(v) else "—")
        mostrar["precio"] = mostrar["precio"].apply(lambda v: format_cop(int(v)) if pd.notna(v) else "—")
        with card(acento="superior"):
            st.dataframe(
                mostrar[
                    [
                        "id",
                        "nombre",
                        "categoria",
                        "stock_actual",
                        "stock_minimo",
                        "costo",
                        "precio",
                        "codigo_barras",
                        "activo",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    with card(acento="izquierdo"):
        with st.expander("Nuevo producto", icon=":material/add_box:"):
            _form_nuevo_producto(ctx, rol)

    if not productos.empty:
        with card(acento="izquierdo"):
            titulo_seccion("Editar / activar / desactivar", centrado=False)
            opciones = {f"{fila['id']} · {fila['nombre']}": fila["id"] for _, fila in productos.iterrows()}
            seleccion = st.selectbox("Producto", options=list(opciones.keys()), key="inv_editar_select")
            if seleccion:
                producto_id = opciones[seleccion]
                _form_editar_producto(ctx, rol, producto_id, productos)


def _form_nuevo_producto(ctx: ViewContext, rol: str) -> None:
    with st.form("form_nuevo_producto"):
        nombre = st.text_input("Nombre *")
        c1, c2 = st.columns(2)
        with c1:
            categoria = st.text_input("Categoría")
            color = st.text_input("Color")
            talla_tamano = st.text_input("Talla / tamaño")
            codigo_barras = st.text_input("Código de barras (opcional)")
        with c2:
            costo = st.number_input("Costo", min_value=0, step=1000, format="%d")
            precio = st.number_input("Precio de venta", min_value=0, step=1000, format="%d")
            stock_minimo = st.number_input("Stock mínimo", min_value=0, step=1, format="%d")
            stock_inicial = st.number_input("Stock inicial", min_value=0, step=1, format="%d")
        proveedor_id = st.text_input("Proveedor (id, opcional)")
        enviado = st.form_submit_button("Crear producto", type="primary")

    if not enviado:
        return

    if not nombre.strip():
        st.error("El nombre es obligatorio.")
        return

    try:
        resultado = inventory.crear_producto(
            ctx.storage,
            rol,
            nombre=nombre,
            usuario_id=getattr(ctx.usuario, "id", ""),
            categoria=categoria,
            color=color,
            talla_tamano=talla_tamano,
            proveedor_id=proveedor_id,
            costo=int(costo),
            precio=int(precio),
            stock_minimo=int(stock_minimo),
            codigo_barras=codigo_barras,
            stock_inicial=int(stock_inicial),
        )
    except PermisoDenegadoError:
        st.error("No tienes permiso para gestionar el inventario.")
        return
    except (ValueError, DineroInvalidoError) as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "crear producto"))
        return

    st.success(f"Producto '{resultado['id']}' creado.")
    for advertencia in resultado["advertencias"]:
        st.warning(advertencia.mensaje)
    ctx.rerun()


def _form_editar_producto(ctx: ViewContext, rol: str, producto_id: str, productos: pd.DataFrame) -> None:
    fila = productos[productos["id"] == producto_id].iloc[0]

    with st.form(f"form_editar_{producto_id}"):
        nombre = st.text_input("Nombre", value=str(fila["nombre"]))
        c1, c2 = st.columns(2)
        with c1:
            categoria = st.text_input("Categoría", value=str(fila["categoria"] or ""))
            color = st.text_input("Color", value=str(fila["color"] or ""))
            talla_tamano = st.text_input("Talla / tamaño", value=str(fila["talla_tamano"] or ""))
            codigo_barras = st.text_input("Código de barras", value=str(fila["codigo_barras"] or ""))
        with c2:
            costo = st.number_input("Costo", min_value=0, step=1000, value=int(fila["costo"] or 0), format="%d")
            precio = st.number_input("Precio de venta", min_value=0, step=1000, value=int(fila["precio"] or 0), format="%d")
            stock_minimo = st.number_input(
                "Stock mínimo", min_value=0, step=1, value=int(fila["stock_minimo"] or 0), format="%d"
            )
        guardar = st.form_submit_button("Guardar cambios", type="primary")

    if guardar:
        try:
            resultado = inventory.editar_producto(
                ctx.storage,
                rol,
                producto_id=producto_id,
                usuario_id=getattr(ctx.usuario, "id", ""),
                nombre=nombre,
                categoria=categoria,
                color=color,
                talla_tamano=talla_tamano,
                costo=int(costo),
                precio=int(precio),
                stock_minimo=int(stock_minimo),
                codigo_barras=codigo_barras,
            )
        except PermisoDenegadoError:
            st.error("No tienes permiso para gestionar el inventario.")
            return
        except (ValueError, DineroInvalidoError) as exc:
            st.error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensivo
            st.error(_mensaje_amigable(exc, "editar producto"))
            return

        st.success("Producto actualizado.")
        for advertencia in resultado["advertencias"]:
            st.warning(advertencia.mensaje)
        ctx.rerun()

    activo = bool(fila["activo"])
    st.markdown(chip_estado("Activo", "exito") if activo else chip_estado("Inactivo", "error", icono="pause_circle"), unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        if activo and st.button("Desactivar producto", key=f"desactivar_{producto_id}", icon=":material/visibility_off:"):
            _cambiar_estado(ctx, rol, producto_id, activo=False)
    with col_b:
        if not activo and st.button("Reactivar producto", key=f"activar_{producto_id}", icon=":material/visibility:"):
            _cambiar_estado(ctx, rol, producto_id, activo=True)


def _cambiar_estado(ctx: ViewContext, rol: str, producto_id: str, *, activo: bool) -> None:
    try:
        if activo:
            inventory.activar_producto(ctx.storage, rol, producto_id=producto_id, usuario_id=getattr(ctx.usuario, "id", ""))
        else:
            inventory.desactivar_producto(ctx.storage, rol, producto_id=producto_id, usuario_id=getattr(ctx.usuario, "id", ""))
    except PermisoDenegadoError:
        st.error("No tienes permiso para gestionar el inventario.")
        return
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "cambiar estado de producto"))
        return
    st.success("Hecho.")
    ctx.rerun()


# ----------------------------------------------------------- Entrada
def _tab_entrada(ctx: ViewContext, rol: str) -> None:
    titulo_seccion("Entrada de mercancía")
    st.caption("Registra mercancía que llega al inventario. El costo promedio se recalcula automáticamente.")

    try:
        productos = inventory.listar_productos(ctx.storage, rol, solo_activos=True)
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "listar productos para entrada"))
        return

    if productos.empty:
        estado_vacio("Todavía no hay productos activos.", "Crea uno en la pestaña 'Productos'.", icono="inventory_2")
        return

    opciones = {f"{fila['id']} · {fila['nombre']}": fila["id"] for _, fila in productos.iterrows()}

    with card(acento="superior"):
        with st.form("form_entrada_mercancia"):
            seleccion = st.selectbox("Producto *", options=list(opciones.keys()))
            cantidad = st.number_input("Cantidad que entra *", min_value=1, step=1, format="%d")
            costo_unitario = st.number_input("Costo unitario de esta entrada *", min_value=0, step=1000, format="%d")
            proveedor_id = st.text_input("Proveedor (id, opcional)")
            documento_ref = st.text_input("Documento de referencia (factura, remisión, opcional)")
            nota = st.text_area("Nota (opcional)")
            enviado = st.form_submit_button("Registrar entrada", type="primary", icon=":material/move_to_inbox:")

    if not enviado:
        return

    producto_id = opciones[seleccion]
    try:
        resultado = costing.registrar_entrada(
            ctx.storage,
            rol,
            producto_id=producto_id,
            cantidad=int(cantidad),
            costo_unitario=int(costo_unitario),
            usuario_id=getattr(ctx.usuario, "id", ""),
            sede_id=SEDE_PRINCIPAL,
            proveedor_id=proveedor_id,
            documento_ref=documento_ref,
            nota=nota,
        )
    except PermisoDenegadoError:
        st.error("No tienes permiso para ajustar el inventario.")
        return
    except (ValueError, DineroInvalidoError) as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "registrar entrada de mercancía"))
        return

    st.success(
        f"Entrada registrada. Stock nuevo: {resultado['stock_nuevo']}. "
        f"Costo promedio nuevo: {format_cop(resultado['costo_nuevo'])}."
    )
    ctx.rerun()


# ------------------------------------------------------------ Conteo físico
def _tab_conteo(ctx: ViewContext, rol: str) -> None:
    titulo_seccion("Conteo físico")
    st.caption("Ingresa lo que contaste; si hay diferencia con el sistema, pide un motivo y ajusta el stock.")

    try:
        productos = inventory.listar_productos(ctx.storage, rol, solo_activos=True)
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "listar productos para conteo"))
        return

    if productos.empty:
        estado_vacio("Todavía no hay productos activos.", icono="inventory_2")
        return

    opciones = {
        f"{fila['id']} · {fila['nombre']} (sistema: {int(fila['stock_actual'])})": fila["id"]
        for _, fila in productos.iterrows()
    }

    with card(acento="superior"):
        with st.form("form_conteo_fisico"):
            seleccion = st.selectbox("Producto *", options=list(opciones.keys()))
            cantidad_contada = st.number_input("Cantidad contada *", min_value=0, step=1, format="%d")
            motivo = st.text_area("Motivo del ajuste (obligatorio solo si hay diferencia)")
            enviado = st.form_submit_button("Registrar conteo", type="primary", icon=":material/fact_check:")

    if not enviado:
        return

    producto_id = opciones[seleccion]
    try:
        resultado = inventory.conteo_fisico(
            ctx.storage,
            rol,
            producto_id=producto_id,
            cantidad_contada=int(cantidad_contada),
            usuario_id=getattr(ctx.usuario, "id", ""),
            motivo=motivo,
            sede_id=SEDE_PRINCIPAL,
        )
    except PermisoDenegadoError:
        st.error("No tienes permiso para ajustar el inventario.")
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "registrar conteo físico"))
        return

    if resultado.diferencia == 0:
        st.success("Sin diferencias: el conteo coincide con el sistema.")
    else:
        st.success(
            f"Ajuste registrado. Diferencia: {resultado.diferencia:+d}. "
            f"Stock sistema: {resultado.stock_sistema} → contado: {resultado.stock_contado}."
        )
    ctx.rerun()


# ------------------------------------------------------------- Importar
def _plantilla_csv_bytes() -> bytes:
    columnas = importer.plantilla_columnas()
    return pd.DataFrame(columns=columnas).to_csv(index=False).encode("utf-8-sig")


def _tab_importar(ctx: ViewContext, rol: str) -> None:
    titulo_seccion("Importar inventario inicial")
    st.caption("Sube un Excel o CSV. Primero verás una vista previa fila por fila; nada se guarda hasta que confirmes.")

    st.download_button(
        "Descargar plantilla (CSV)",
        data=_plantilla_csv_bytes(),
        file_name="plantilla_inventario_ola_tata.csv",
        mime="text/csv",
        icon=":material/download:",
    )

    archivo = st.file_uploader("Archivo de inventario (.xlsx o .csv)", type=["xlsx", "csv"])
    if archivo is None:
        return

    try:
        if archivo.name.lower().endswith(".csv"):
            df = pd.read_csv(archivo, dtype=object)
        else:
            df = pd.read_excel(archivo, dtype=object)
    except Exception as exc:
        st.error(_mensaje_amigable(exc, "leer archivo de importación"))
        return

    try:
        resultado = importer.validar_filas(ctx.storage, df)
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "validar importación"))
        return

    st.markdown(f"**{len(resultado.filas_validas)} fila(s) válidas** · **{len(resultado.errores)} error(es)**")

    if resultado.errores:
        st.error("Hay errores en algunas filas. Corrígelas y vuelve a subir el archivo; no se importó nada.")
        st.dataframe(
            pd.DataFrame([{"fila": e.fila, "columna": e.columna, "error": e.mensaje} for e in resultado.errores]),
            use_container_width=True,
            hide_index=True,
        )

    if resultado.advertencias:
        st.warning("Hay advertencias (no bloquean la importación):")
        st.dataframe(
            pd.DataFrame(
                [{"fila": a.fila, "columna": a.columna, "advertencia": a.mensaje} for a in resultado.advertencias]
            ),
            use_container_width=True,
            hide_index=True,
        )

    if resultado.filas_validas:
        st.markdown("**Vista previa de lo que se va a importar:**")
        st.dataframe(pd.DataFrame(resultado.filas_validas), use_container_width=True, hide_index=True)

    if resultado.ok and resultado.filas_validas:
        confirmar = st.checkbox("Confirmo que revisé la vista previa y quiero importar estas filas.")
        if st.button("Importar inventario inicial", type="primary", disabled=not confirmar, icon=":material/upload_file:"):
            try:
                resumen = importer.aplicar_importacion(
                    ctx.storage,
                    rol,
                    filas=df,
                    usuario_id=getattr(ctx.usuario, "id", ""),
                    confirmar=True,
                    sede_id=SEDE_PRINCIPAL,
                )
            except PermisoDenegadoError:
                st.error("No tienes permiso para importar inventario.")
                return
            except ValueError as exc:
                st.error(str(exc))
                return
            except Exception as exc:  # pragma: no cover - defensivo
                st.error(_mensaje_amigable(exc, "aplicar importación"))
                return
            st.success(f"Se crearon {resumen['creados']} producto(s).")
            ctx.rerun()


# ------------------------------------------------------------- Etiquetas
def _tab_etiquetas(ctx: ViewContext, rol: str) -> None:
    titulo_seccion("Etiquetas con código de barras")

    try:
        requerir(rol, "etiquetas")
    except PermisoDenegadoError:
        st.error("No tienes permiso para generar etiquetas.")
        return

    try:
        productos = inventory.listar_productos(ctx.storage, rol, solo_activos=True)
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "listar productos para etiquetas"))
        return

    con_codigo = productos[productos["codigo_barras"].astype(str).str.strip() != ""]
    if con_codigo.empty:
        estado_vacio("Ningún producto activo tiene código de barras asignado todavía.", icono="qr_code")
        return

    opciones = {f"{fila['id']} · {fila['nombre']}": fila["id"] for _, fila in con_codigo.iterrows()}
    seleccionados = st.multiselect("Productos a imprimir", options=list(opciones.keys()))
    incluir_precio = st.checkbox("Incluir precio en la etiqueta", value=True)

    if st.button("Generar PDF de etiquetas", type="primary", disabled=not seleccionados, icon=":material/qr_code_2:"):
        filas = con_codigo[con_codigo["id"].isin([opciones[s] for s in seleccionados])]
        datos = [
            {
                "nombre": fila["nombre"],
                "codigo_barras": fila["codigo_barras"],
                "precio": int(fila["precio"]) if incluir_precio and pd.notna(fila["precio"]) else None,
            }
            for _, fila in filas.iterrows()
        ]
        try:
            pdf_bytes = labels_ot.generar_pdf_etiquetas(datos)
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensivo
            st.error(_mensaje_amigable(exc, "generar etiquetas"))
            return
        st.download_button(
            "Descargar PDF de etiquetas",
            data=pdf_bytes,
            file_name="etiquetas_ola_tata.pdf",
            mime="application/pdf",
        )


# ----------------------------------------------------------- Integridad
def _tab_integridad(ctx: ViewContext, rol: str) -> None:
    titulo_seccion("Verificar integridad del inventario")
    st.caption("Recalcula el stock de cada producto desde el kardex de movimientos y lo compara con el sistema.")

    if st.button("Verificar integridad ahora", type="primary", icon=":material/fact_check:"):
        try:
            diferencias = inventory.verificar_integridad(ctx.storage, rol)
        except PermisoDenegadoError:
            st.error("No tienes permiso para verificar la integridad del inventario.")
            return
        except Exception as exc:  # pragma: no cover - defensivo
            st.error(_mensaje_amigable(exc, "verificar integridad"))
            return

        if not diferencias:
            st.success("Todo cuadra: el stock de cada producto coincide con su historial de movimientos.")
        else:
            st.error(f"Se encontraron {len(diferencias)} diferencia(s). Revisa el kardex de estos productos.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "producto_id": d.producto_id,
                            "sede": d.sede_id,
                            "stock_en_hoja": d.stock_en_hoja,
                            "stock_recalculado": d.stock_recalculado,
                            "diferencia": d.diferencia,
                        }
                        for d in diferencias
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
