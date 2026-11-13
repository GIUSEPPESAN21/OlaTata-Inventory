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

from core import costing, etiquetas, importer, inventory, schema
from core.money import DineroInvalidoError, format_cop
from core.permissions import PermisoDenegadoError, requerir, tiene_capacidad
from core.schema import SEDE_PRINCIPAL
from core.ui import (
    boton_imprimir_pdf,
    tabla_html,
    boton_ver_mas,
    chip_stock,
    fila_html,
    limite_paginado,
    card,
    chip_estado,
    encabezado_pagina,
    estado_vacio,
    guia,
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

    # Pestañas con memoria (key + on_change): conservan la pestaña elegida
    # entre clics y SOLO se ejecuta la visible (antes corrían las 6 en cada
    # clic, incluida la generación del PDF de etiquetas).
    secciones = [
        ("Productos", _tab_productos),
        ("Entrada de mercancía", _tab_entrada),
        ("Conteo físico", _tab_conteo),
        ("Importar inventario", _tab_importar),
        ("Etiquetas", _tab_etiquetas),
        ("Integridad", _tab_integridad),
    ]
    tabs = st.tabs([n for n, _ in secciones], key="inventario_pestana", on_change="rerun")
    for tab, (_nombre, funcion) in zip(tabs, secciones):
        with tab:
            if tab.open:
                funcion(ctx, rol)


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

    with card(acento="izquierdo"):
        with st.expander("Nuevo producto", icon=":material/add_box:", key="inv_exp_nuevo_producto"):
            _form_nuevo_producto(ctx, rol)

    if filtrados.empty:
        estado_vacio(
            "No hay productos que coincidan con estos filtros.",
            "Crea uno nuevo con «Nuevo producto».",
            icono="search_off",
        )
        return

    firma = f"{busqueda}|{categoria}|{bajo_minimo}|{sin_stock}"
    limite = limite_paginado("inv_lista", firma, paso=20)
    abierto = st.session_state.get("inv_producto_sel")
    st.caption(f"{len(filtrados)} producto(s). Pulsa «Editar» para cambiar datos, precio o desactivarlo.")
    for _, fila in filtrados.head(limite).iterrows():
        _fila_producto(ctx, rol, fila, abierto, productos)
    boton_ver_mas("inv_lista", len(filtrados), min(limite, len(filtrados)), paso=20)


def _seleccionar_producto(producto_id: str | None) -> None:
    st.session_state["inv_producto_sel"] = producto_id


def _fila_producto(ctx: ViewContext, rol: str, fila, abierto, productos: pd.DataFrame) -> None:
    """Fila de producto: nombre, categoría/código, precio y existencias.
    Al pulsar "Editar" el formulario se abre justo debajo."""
    pid = str(fila["id"])
    es_abierto = abierto == pid

    def _txt(valor) -> str:
        return "" if pd.isna(valor) else str(valor).strip()

    sub = " · ".join(x for x in (_txt(fila["categoria"]), _txt(fila["color"]),
                                  etiquetas.codigo_para_producto(pid, _txt(fila["codigo_barras"]))) if x)
    precio = format_cop(int(fila["precio"])) if pd.notna(fila["precio"]) else "—"
    minimo = int(fila["stock_minimo"]) if pd.notna(fila["stock_minimo"]) else 0
    chips = chip_stock(int(fila["stock_actual"]), minimo, bool(fila["activo"]))
    with st.container(key=f"ot-fila-{'sel-' if es_abierto else ''}producto-{pid}"):
        c1, c2 = st.columns([10, 2], vertical_alignment="center")
        c1.markdown(fila_html(_txt(fila["nombre"]), sub=sub, valor=precio, chips_html=chips), unsafe_allow_html=True)
        c2.button(
            "Cerrar" if es_abierto else "Editar",
            key=f"inv_editar_{pid}",
            icon=":material/close:" if es_abierto else ":material/edit:",
            on_click=_seleccionar_producto,
            args=(None if es_abierto else pid,),
            use_container_width=True,
        )
    if es_abierto:
        with card(acento="izquierdo", key="ot-card-detalle-producto"):
            _form_editar_producto(ctx, rol, pid, productos)


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
        data=_plantilla_csv_bytes,
        on_click="ignore",
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
        tabla_html(
            [{"fila": e.fila, "columna": e.columna, "mensaje": e.mensaje} for e in resultado.errores],
            [{"clave": "fila", "titulo": "Fila", "tipo": "numero"}, {"clave": "columna", "titulo": "Columna"},
             {"clave": "mensaje", "titulo": "Qué corregir", "destacar": True}],
        )

    if resultado.advertencias:
        st.warning("Hay advertencias (no bloquean la importación):")
        tabla_html(
            [{"fila": a.fila, "columna": a.columna, "mensaje": a.mensaje} for a in resultado.advertencias],
            [{"clave": "fila", "titulo": "Fila", "tipo": "numero"}, {"clave": "columna", "titulo": "Columna"},
             {"clave": "mensaje", "titulo": "Advertencia"}],
        )

    if resultado.filas_validas:
        titulo_seccion("Vista previa de lo que se va a importar")
        vista = resultado.filas_validas[:50]
        tabla_html(
            vista,
            [{"clave": "nombre", "titulo": "Producto", "destacar": True}, {"clave": "categoria", "titulo": "Categoría"},
             {"clave": "precio", "titulo": "Precio", "tipo": "dinero"},
             {"clave": "cantidad_inicial", "titulo": "Unidades", "tipo": "numero"}],
        )
        if len(resultado.filas_validas) > len(vista):
            st.caption(f"…y {len(resultado.filas_validas) - len(vista)} producto(s) más.")

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
        # Buscador con escritura: se escribe parte del nombre o del código y
        # se eligen los productos (antes: cuadrícula con casillas).
        por_id = productos.set_index(productos["id"].astype(str))
        opciones = list(por_id.index)

        def _etiqueta_opcion(pid: str) -> str:
            fila = por_id.loc[pid]
            precio = format_cop(int(fila["precio"])) if pd.notna(fila["precio"]) else "—"
            codigo = etiquetas.codigo_para_producto(pid, fila.get("codigo_barras"))
            return f"{fila['nombre']} · {precio} · {int(fila['stock_actual'])} en stock · {codigo}"

        elegidos_ids = st.multiselect(
            "Productos",
            opciones,
            format_func=_etiqueta_opcion,
            key="etq_productos",
            placeholder="Escribe el nombre o el código y elige…",
        )
        incluir_precio = st.checkbox("Incluir precio en la etiqueta", value=True, key="etq_precio")
        cantidades: dict[str, int] = {}
        if elegidos_ids:
            st.caption("Cantidad de etiquetas por producto (por defecto, una por unidad en stock):")
        for pid in elegidos_ids:
            fila = por_id.loc[pid]
            c1, c2 = st.columns([7, 2], vertical_alignment="center")
            c1.markdown(
                fila_html(str(fila["nombre"]), sub=etiquetas.codigo_para_producto(pid, fila.get("codigo_barras"))),
                unsafe_allow_html=True,
            )
            cantidades[pid] = int(c2.number_input(
                "Etiquetas", min_value=1, max_value=500, step=1, key=f"etq_cant_{pid}",
                value=max(1, int(fila["stock_actual"])), label_visibility="collapsed",
            ))

    if not elegidos_ids:
        st.caption("Busca y elige los productos a etiquetar en el campo **Productos**.")
        return

    items: list[etiquetas.ItemEtiqueta] = []
    codigos_largos: list[str] = []
    for pid in elegidos_ids:
        prod = por_id.loc[pid]
        codigo = etiquetas.codigo_para_producto(pid, prod.get("codigo_barras"))
        if etiquetas.modulo_barras_px(codigo, perfil.mm_a_px(perfil.ancho_mm - 2.4)) < 2:
            codigos_largos.append(f"{prod['nombre']} ({codigo})")
        precio = int(prod["precio"]) if incluir_precio and pd.notna(prod["precio"]) else None
        items += [etiquetas.ItemEtiqueta(str(prod["nombre"]), codigo, precio)] * cantidades.get(pid, 1)

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
        with st.expander("Avanzado: enviar directo a la impresora (TSPL)", icon=":material/terminal:",
                         key="inv_exp_tspl"):
            st.caption(
                "Si el driver de Windows recorta o escala las etiquetas, este archivo va directo a la "
                "impresora sin driver (ver docs/IMPRESORAS.md). Es la misma imagen del PDF."
            )
            invertir = st.checkbox("Invertir blanco/negro (solo si sale en negativo)", key="etq_tspl_inv")
            st.download_button(
                "Descargar archivo TSPL (.prn)",
                # Se genera solo al pulsar (no en cada clic de la pantalla).
                data=lambda items=items, perfil=perfil, invertir=invertir: etiquetas.generar_tspl(
                    items, perfil, invertir=invertir
                ),
                on_click="ignore",
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
                         key=f"inv_exp_medidas_{eleccion}",
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
            productos_todos = ctx.storage.read_sheet(schema.PRODUCTOS)
            nombres = dict(zip(productos_todos["id"].astype(str), productos_todos["nombre"].astype(str)))
            tabla_html(
                [
                    {"producto": nombres.get(str(d.producto_id), str(d.producto_id)),
                     "registrado": d.stock_en_hoja, "real": d.stock_recalculado, "diferencia": d.diferencia}
                    for d in diferencias
                ],
                [{"clave": "producto", "titulo": "Producto", "destacar": True},
                 {"clave": "registrado", "titulo": "Stock registrado", "tipo": "numero"},
                 {"clave": "real", "titulo": "Según movimientos", "tipo": "numero"},
                 {"clave": "diferencia", "titulo": "Diferencia", "tipo": "numero", "destacar": True}],
            )
