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

from core import costing, etiquetas, importer, inventory
from core.money import DineroInvalidoError, format_cop
from core.permissions import PermisoDenegadoError, requerir, tiene_capacidad
from core.schema import SEDE_PRINCIPAL
from core.ui import (
    boton_imprimir_pdf,
    card,
    chip_estado,
    encabezado_pagina,
    estado_vacio,
    guia,
    tabla_amigable,
    titulo_seccion,
)
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
    guia("inventario")

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
    guia("inventario_productos")
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
                tabla_amigable(
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
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    with card(acento="izquierdo"):
        with st.expander("Nuevo producto", icon=":material/add_box:"):
            _form_nuevo_producto(ctx, rol)

    if not productos.empty:
        with card(acento="izquierdo"):
            titulo_seccion("Editar / activar / desactivar")
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

    # Celda vacía en la hoja = NaN (float); "NaN or ''" en Python sigue
    # siendo NaN (un float NaN es verdadero), así que el campo mostraba
    # literalmente "nan" en vez de quedar vacío (capa visual: hallazgo de
    # A5 durante la verificación visual, ver informe final).
    def _texto_o_vacio(valor) -> str:
        return "" if pd.isna(valor) else str(valor)

    with st.form(f"form_editar_{producto_id}"):
        nombre = st.text_input("Nombre", value=str(fila["nombre"]))
        c1, c2 = st.columns(2)
        with c1:
            categoria = st.text_input("Categoría", value=_texto_o_vacio(fila["categoria"]))
            color = st.text_input("Color", value=_texto_o_vacio(fila["color"]))
            talla_tamano = st.text_input("Talla / tamaño", value=_texto_o_vacio(fila["talla_tamano"]))
            codigo_barras = st.text_input("Código de barras", value=_texto_o_vacio(fila["codigo_barras"]))
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
    guia("inventario_entrada")
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
    guia("inventario_conteo")
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
    guia("inventario_importar")
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
            tabla_amigable(pd.DataFrame([{"fila": e.fila, "columna": e.columna, "error": e.mensaje} for e in resultado.errores])),
            use_container_width=True,
            hide_index=True,
        )

    if resultado.advertencias:
        st.warning("Hay advertencias (no bloquean la importación):")
        st.dataframe(
            tabla_amigable(
                pd.DataFrame(
                    [{"fila": a.fila, "columna": a.columna, "advertencia": a.mensaje} for a in resultado.advertencias]
                )
            ),
            use_container_width=True,
            hide_index=True,
        )

    if resultado.filas_validas:
        titulo_seccion("Vista previa de lo que se va a importar")
        st.dataframe(tabla_amigable(pd.DataFrame(resultado.filas_validas)), use_container_width=True, hide_index=True)

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
_PERSONALIZADO = "Personalizado…"


def _tab_etiquetas(ctx: ViewContext, rol: str) -> None:
    """Etiquetas de precio para la impresora DigitalPOS de etiquetas.

    Prioridad del diseño: artículo, código de barras y precio (ver
    `core/etiquetas.py`). El PDF sale al tamaño FÍSICO del rollo; el
    perfil (medidas, etiquetas por fila) se guarda en CONFIG para que el
    día de la instalación se ajuste sin tocar código."""
    titulo_seccion("Etiquetas de precio")
    guia("inventario_etiquetas")

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
    if productos.empty:
        estado_vacio("Todavía no hay productos activos.", "Crea productos en la pestaña Productos.", icono="sell")
        return

    perfil = _seccion_perfil_etiquetas(ctx, rol)
    if perfil is None:
        return

    with card(acento="superior"):
        titulo_seccion("¿Qué etiquetas imprimir?")
        busqueda = st.text_input("Filtrar productos", key="etq_filtro", icon=":material/search:")
        tabla = productos.copy()
        if busqueda.strip():
            patron = busqueda.strip().lower()
            tabla = tabla[
                tabla["nombre"].astype(str).str.lower().str.contains(patron, regex=False)
                | tabla["id"].astype(str).str.lower().str.contains(patron, regex=False)
            ]
        editor = pd.DataFrame(
            {
                "imprimir": False,
                "id": tabla["id"].astype(str),
                "producto": tabla["nombre"].astype(str),
                "precio": tabla["precio"].apply(lambda v: format_cop(int(v)) if pd.notna(v) else "—"),
                "stock": tabla["stock_actual"].astype(int),
                "cantidad": tabla["stock_actual"].astype(int).clip(lower=1),
            }
        )
        editado = st.data_editor(
            editor,
            hide_index=True,
            use_container_width=True,
            key=f"etq_editor_{busqueda.strip().lower()}",
            disabled=["id", "producto", "precio", "stock"],
            column_config={
                "imprimir": st.column_config.CheckboxColumn("Imprimir"),
                "id": st.column_config.TextColumn("Código"),
                "producto": st.column_config.TextColumn("Producto"),
                "precio": st.column_config.TextColumn("Precio"),
                "stock": st.column_config.NumberColumn("Stock"),
                "cantidad": st.column_config.NumberColumn("Cantidad de etiquetas", min_value=1, max_value=500, step=1),
            },
        )
        incluir_precio = st.checkbox("Incluir precio en la etiqueta", value=True, key="etq_precio")

    elegidos = editado[editado["imprimir"]]
    if elegidos.empty:
        st.caption("Marca la casilla **Imprimir** de cada producto (por defecto, una etiqueta por unidad en stock).")
        return

    por_id = productos.set_index(productos["id"].astype(str))
    items: list[etiquetas.ItemEtiqueta] = []
    codigos_largos: list[str] = []
    for _, fila in elegidos.iterrows():
        prod = por_id.loc[fila["id"]]
        codigo = etiquetas.codigo_para_producto(fila["id"], prod.get("codigo_barras"))
        if etiquetas.modulo_barras_px(codigo, perfil.mm_a_px(perfil.ancho_mm - 2.4)) < 2:
            codigos_largos.append(f"{prod['nombre']} ({codigo})")
        precio = int(prod["precio"]) if incluir_precio and pd.notna(prod["precio"]) else None
        items += [etiquetas.ItemEtiqueta(str(prod["nombre"]), codigo, precio)] * int(fila["cantidad"] or 1)

    filas = (len(items) + perfil.columnas - 1) // perfil.columnas
    st.markdown(
        chip_estado(f"{len(items)} etiqueta(s) · {filas} fila(s) del rollo", "info", icono="sell"),
        unsafe_allow_html=True,
    )
    if codigos_largos:
        st.warning(
            "Estos códigos de barras son largos para el ancho de la etiqueta y las barras salen muy finas "
            "(el lector podría fallar). Prueba a escanear una antes de imprimir todas: "
            + ", ".join(codigos_largos)
        )

    try:
        vista = etiquetas.componer_filas(items[: perfil.columnas], perfil)[0]
        pdf_bytes = etiquetas.generar_pdf(items, perfil)
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensivo
        st.error(_mensaje_amigable(exc, "generar etiquetas"))
        return

    with card(acento="izquierdo"):
        titulo_seccion("Vista previa (primera fila)")
        st.image(vista.convert("L"), use_container_width=True)
        st.caption(
            f"En el diálogo de impresión: impresora de **etiquetas**, papel **{perfil.descripcion_papel}**, "
            "escala **100 % / tamaño real**, sin márgenes."
        )
        etiquetas_pdf_boton(pdf_bytes)
        with st.expander("Avanzado: enviar directo a la impresora (TSPL)", icon=":material/terminal:"):
            st.caption(
                "Si el driver de Windows recorta o escala las etiquetas, este archivo va directo a la "
                "impresora sin driver (ver docs/IMPRESORAS.md). Es la misma imagen del PDF."
            )
            invertir = st.checkbox("Invertir blanco/negro (solo si sale en negativo)", key="etq_tspl_inv")
            st.download_button(
                "Descargar archivo TSPL (.prn)",
                data=etiquetas.generar_tspl(items, perfil, invertir=invertir),
                file_name="etiquetas_ola_tata.prn",
                mime="application/octet-stream",
                icon=":material/download:",
            )


def etiquetas_pdf_boton(pdf_bytes: bytes) -> None:
    boton_imprimir_pdf(pdf_bytes, "Imprimir etiquetas", nombre_archivo="etiquetas_ola_tata.pdf", key="etq_pdf")


def _seccion_perfil_etiquetas(ctx: ViewContext, rol: str):
    """Elige/ajusta el rollo. Devuelve el `PerfilEtiqueta` en uso."""
    guardado = etiquetas.cargar_perfil(ctx.storage)
    with card(acento="superior"):
        titulo_seccion("Impresora y rollo de etiquetas")
        nombres = list(etiquetas.PERFILES_PREDEFINIDOS) + [_PERSONALIZADO]
        indice = nombres.index(guardado.nombre) if guardado.nombre in nombres else len(nombres) - 1
        eleccion = st.selectbox("Tamaño del rollo", nombres, index=indice, key="etq_perfil_sel")
        base = etiquetas.PERFILES_PREDEFINIDOS.get(eleccion, guardado)

        with st.expander("Ajustar medidas (mídelas con una regla)", icon=":material/straighten:",
                         expanded=eleccion == _PERSONALIZADO):
            c1, c2, c3 = st.columns(3)
            ancho = c1.number_input("Ancho etiqueta (mm)", 10.0, 120.0, float(base.ancho_mm), 0.5, key=f"etq_w_{eleccion}")
            alto = c2.number_input("Alto etiqueta (mm)", 10.0, 120.0, float(base.alto_mm), 0.5, key=f"etq_h_{eleccion}")
            columnas = c3.number_input("Etiquetas por fila", 1, 4, int(base.columnas), 1, key=f"etq_c_{eleccion}")
            c4, c5, c6 = st.columns(3)
            separacion = c4.number_input("Separación entre etiquetas (mm)", 0.0, 20.0, float(base.separacion_mm), 0.5,
                                         key=f"etq_s_{eleccion}")
            margen = c5.number_input("Margen izquierdo (mm)", 0.0, 20.0, float(base.margen_izq_mm), 0.5,
                                     key=f"etq_m_{eleccion}")
            gap = c6.number_input("Espacio entre filas (mm)", 0.0, 10.0, float(base.gap_vertical_mm), 0.5,
                                  key=f"etq_g_{eleccion}")
            dpi = st.radio("Resolución de la impresora", [203, 300], index=0 if base.dpi == 203 else 1,
                           horizontal=True, key=f"etq_dpi_{eleccion}",
                           format_func=lambda d: f"{d} dpi" + (" (la más común)" if d == 203 else ""))
        try:
            perfil = etiquetas.PerfilEtiqueta(
                nombre=eleccion if eleccion != _PERSONALIZADO else _PERSONALIZADO,
                ancho_mm=ancho, alto_mm=alto, columnas=int(columnas), separacion_mm=separacion,
                margen_izq_mm=margen, gap_vertical_mm=gap, dpi=int(dpi),
            )
        except ValueError as exc:
            st.error(str(exc))
            return None
        if perfil != base and eleccion != _PERSONALIZADO:
            perfil = etiquetas.con_perfil(perfil, nombre=_PERSONALIZADO)

        st.markdown(
            chip_estado(f"Papel en el driver: {perfil.descripcion_papel}", "info", icono="print"),
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        if col_a.button("Guardar como predeterminado", icon=":material/save:", use_container_width=True,
                        disabled=perfil == guardado):
            try:
                with ctx.storage.transaction() as tx:
                    etiquetas.guardar_perfil(tx, rol, perfil)
            except PermisoDenegadoError:
                st.error("No tienes permiso para cambiar el perfil de etiquetas.")
            except Exception as exc:  # pragma: no cover - defensivo
                st.error(_mensaje_amigable(exc, "guardar perfil de etiquetas"))
            else:
                st.success("Perfil guardado.")
        with col_b:
            with st.popover("Hoja de prueba", icon=":material/grid_on:", use_container_width=True):
                st.caption(
                    "Imprime UNA fila con el borde de cada etiqueta. Si los recuadros caen dentro de las "
                    "etiquetas del rollo, las medidas están bien."
                )
                boton_imprimir_pdf(etiquetas.generar_pdf_calibracion(perfil), "Imprimir hoja de prueba",
                                   nombre_archivo="prueba_etiquetas.pdf", key="etq_calibracion")
    return perfil


# ----------------------------------------------------------- Integridad
def _tab_integridad(ctx: ViewContext, rol: str) -> None:
    guia("inventario_integridad")
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
                tabla_amigable(pd.DataFrame(
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
                )),
                use_container_width=True,
                hide_index=True,
            )
