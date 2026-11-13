"""Vista: Ventas. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`.

Historial en UNA tabla con todas las ventas del rango visibles de una vez
y búsqueda EN TIEMPO REAL (número, cliente, teléfono, producto, código o
vendedor; sin Enter). Al tocar una fila aparece su detalle con las
acciones: reimprimir recibo, editar datos (maestro), anular (admin y
maestro, con motivo) y devolución/cambio -- §6.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from core import schema
from core.busqueda import normalizar
from core.edicion_ventas import editar_venta
from core.etiquetas import codigo_para_producto
from core.money import format_cop
from core.permissions import PermisoDenegadoError, tiene_capacidad
from core.recibo_impreso import generar_pdf_recibo
from core.returns import DevolucionInvalidaError, VentaNoEncontradaError, anular_venta, registrar_devolucion_cambio
from core.schema import CANALES_VENTA
from core.timeutil import local_date, now_utc, parse_iso_utc
from core.ui import (
    boton_imprimir_pdf,
    card,
    chip_estado,
    encabezado_pagina,
    estado_vacio,
    formatear_fecha_hora_local,
    guia,
    md_seguro,
    mensaje_error_amable,
    titulo_seccion,
)
from views import ViewContext

_METODOS_LABEL = {
    "efectivo": "Efectivo",
    "datafono": "Datáfono",
    "transferencia": "Transferencia",
    "sistecredito": "Sistecrédito",
    "cambio": "Cambio (saldo a favor)",
}


def render(ctx: ViewContext) -> None:
    storage = ctx.storage
    usuario = ctx.usuario

    encabezado_pagina("Ventas", "Historial, devoluciones y anulaciones", icono="receipt_long")
    guia("ventas")

    ventas_df = storage.read_sheet(schema.VENTAS)
    if ventas_df.empty:
        estado_vacio("Todavía no se ha registrado ninguna venta.", icono="receipt_long")
        return

    with card(acento="superior", key="ot-card-ventas-filtros"):
        col1, col2, col3 = st.columns([2, 2, 5])
        hoy = local_date(now_utc())
        desde = col1.date_input("Desde", value=hoy - timedelta(days=7), key="ventas_desde", format="DD/MM/YYYY")
        hasta = col2.date_input("Hasta", value=hoy, key="ventas_hasta", format="DD/MM/YYYY")
        consulta = col3.text_input(
            "Buscar",
            key="ventas_q",
            live="300ms",
            placeholder="Número, cliente, teléfono, producto, código o vendedor",
            icon=":material/search:",
        )

    ventas_df = ventas_df[
        (ventas_df["fecha_local"].astype(str) >= desde.isoformat()) & (ventas_df["fecha_local"].astype(str) <= hasta.isoformat())
    ]
    if not tiene_capacidad(usuario.rol, "ver_ventas_todas"):
        ventas_df = ventas_df[ventas_df["vendedor_id"] == usuario.id]

    items_df = storage.read_sheet(schema.VENTA_ITEMS)
    pagos_df = storage.read_sheet(schema.PAGOS)
    productos_df = storage.read_sheet(schema.PRODUCTOS)
    tabla, ventas_df = _tabla_ventas(ventas_df, items_df, pagos_df, productos_df, consulta)

    confirmadas = ventas_df[ventas_df["estado"] != "anulada"]
    total = int(pd.to_numeric(confirmadas["total"], errors="coerce").fillna(0).sum())
    k1, k2, k3 = st.columns(3)
    k1.markdown(_mini_kpi("Ventas", str(len(confirmadas)), "receipt_long"), unsafe_allow_html=True)
    k2.markdown(_mini_kpi("Total vendido", format_cop(total), "payments"), unsafe_allow_html=True)
    k3.markdown(_mini_kpi("Anuladas", str(len(ventas_df) - len(confirmadas)), "cancel"), unsafe_allow_html=True)

    if tabla.empty:
        estado_vacio(
            "No hay ventas que coincidan." if consulta.strip() else "No hay ventas en ese rango de fechas.",
            "Prueba con otras fechas u otra búsqueda.",
            icono="search_off",
        )
        return

    # La clave incluye los filtros: si cambian, la fila elegida se limpia
    # (así nunca queda seleccionada otra venta por error).
    clave_tabla = f"ventas_tabla_{desde}_{hasta}_{normalizar(consulta)}"
    evento = st.dataframe(
        tabla,
        key=clave_tabla,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        use_container_width=True,
        height=min(500, 46 + 39 * len(tabla)),
        column_config={
            "Número": st.column_config.TextColumn("Número", width=150),
            "Fecha y hora": st.column_config.TextColumn("Fecha y hora", width=195),
            "Cliente": st.column_config.TextColumn("Cliente", width=150),
            "Productos": st.column_config.TextColumn("Productos", width="large"),
            "Total": st.column_config.TextColumn("Total", width=110),
            "Pago": st.column_config.TextColumn("Pago", width=120),
            "Vendedor": st.column_config.TextColumn("Vendedor", width=140),
            "Estado": st.column_config.TextColumn("Estado", width=105),
        },
    )
    filas = list(getattr(getattr(evento, "selection", None), "rows", []) or [])
    if not filas:
        st.caption("Toca una venta de la tabla para ver el detalle, reimprimir el recibo, editarla, anularla o registrar una devolución.")
        return
    venta = ventas_df.iloc[filas[0]]
    _detalle_venta(
        ctx,
        venta,
        items_df[items_df["venta_id"] == venta["id"]],
        pagos_df[pagos_df["venta_id"] == venta["id"]],
    )


def _mini_kpi(etiqueta: str, valor: str, icono: str) -> str:
    return (
        '<div class="ot-mini-kpi">'
        f'<span class="material-symbols-outlined">{icono}</span>'
        f'<div><div class="ot-mini-kpi__valor">{valor}</div><div class="ot-mini-kpi__etiqueta">{etiqueta}</div></div>'
        "</div>"
    )


def _texto(valor) -> str:
    return "" if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else str(valor)


def _tabla_ventas(ventas_df, items_df, pagos_df, productos_df, consulta: str):
    """Arma la tabla visible (una fila por venta) y filtra por la búsqueda.
    Devuelve (tabla_para_mostrar, ventas_filtradas_en_el_mismo_orden)."""
    ventas_df = ventas_df.sort_values("fecha_hora_utc", ascending=False).reset_index(drop=True)
    codigos = {
        str(f["id"]): codigo_para_producto(str(f["id"]), _texto(f.get("codigo_barras")))
        for _, f in productos_df.iterrows()
    }
    filas, indices = [], []
    for _, venta in ventas_df.iterrows():
        items = items_df[items_df["venta_id"] == venta["id"]]
        pagos = pagos_df[pagos_df["venta_id"] == venta["id"]]
        productos_txt = ", ".join(f"{int(i['cantidad'])}× {_texto(i['nombre_snapshot'])}" for _, i in items.iterrows())
        metodos = ", ".join(dict.fromkeys(_METODOS_LABEL.get(str(m), str(m)) for m in pagos["metodo"]))
        try:
            fecha = formatear_fecha_hora_local(parse_iso_utc(str(venta["fecha_hora_utc"])))
        except Exception:
            fecha = _texto(venta["fecha_local"])
        filas.append({
            "Número": _texto(venta["numero"]),
            "Fecha y hora": fecha,
            "Cliente": _texto(venta["cliente_nombre"]) or "—",
            "Productos": productos_txt or "—",
            "Total": format_cop(int(venta["total"])),
            "Pago": metodos or "—",
            "Vendedor": _texto(venta["vendedor_nombre"]),
            "Estado": "Anulada" if venta["estado"] == "anulada" else "Confirmada",
        })
        indices.append(normalizar(" ".join([
            _texto(venta["numero"]), _texto(venta["cliente_nombre"]), _texto(venta["cliente_telefono"]),
            _texto(venta["vendedor_nombre"]), _texto(venta["canal"]), productos_txt,
            " ".join(str(i) for i in items["producto_id"]), " ".join(codigos.get(str(i), "") for i in items["producto_id"]),
        ])))
    tabla = pd.DataFrame(filas)
    palabras = normalizar(consulta).split()
    if palabras and not tabla.empty:
        coincide = [all(p in idx for p in palabras) for idx in indices]
        tabla = tabla[coincide].reset_index(drop=True)
        ventas_df = ventas_df[coincide].reset_index(drop=True)
    return tabla, ventas_df


def _detalle_venta(ctx: ViewContext, venta, items_venta, pagos_venta) -> None:
    usuario = ctx.usuario
    anulada = venta["estado"] == "anulada"
    with card(acento="izquierdo", key="ot-card-ventas-detalle"):
        titulo_seccion(f"Venta {_texto(venta['numero'])}")
        st.markdown(
            chip_estado("Anulada", "error") if anulada else chip_estado("Confirmada", "exito"),
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Vendedor:** {md_seguro(_texto(venta['vendedor_nombre']))}")
            st.markdown(f"**Canal:** {md_seguro(_texto(venta['canal']).capitalize())}")
            if _texto(venta["cliente_nombre"]).strip():
                telefono = f" · {md_seguro(_texto(venta['cliente_telefono']))}" if _texto(venta["cliente_telefono"]).strip() else ""
                st.markdown(f"**Cliente:** {md_seguro(_texto(venta['cliente_nombre']))}{telefono}")
            envio = [x for x in (_texto(venta.get("envio_ciudad")), _texto(venta.get("envio_transportadora")),
                                 _texto(venta.get("envio_guia"))) if x.strip()]
            if envio:
                st.markdown("**Envío:** " + " · ".join(md_seguro(x) for x in envio))
            if _texto(venta.get("nota")).strip():
                st.markdown(f"**Nota:** {md_seguro(_texto(venta['nota']))}")
        with col_b:
            for _, item in items_venta.iterrows():
                st.markdown(
                    f"{int(item['cantidad'])} × {md_seguro(_texto(item['nombre_snapshot']))} — "
                    f"{md_seguro(format_cop(int(item['total_linea'])))}"
                )
            st.markdown(f"**Total: {md_seguro(format_cop(int(venta['total'])))}**")
        if anulada:
            st.error(f"Anulada. Motivo: {md_seguro(_texto(venta['anulada_motivo']))}")

        acciones = ["recibo"]
        if not anulada and tiene_capacidad(usuario.rol, "editar_venta"):
            acciones.append("editar")
        if not anulada and tiene_capacidad(usuario.rol, "anular_venta"):
            acciones.append("anular")
        if not anulada and tiene_capacidad(usuario.rol, "devolucion_cambio"):
            acciones.append("devolucion")
        cols = st.columns(len(acciones))
        for col, accion in zip(cols, acciones):
            with col:
                if accion == "recibo":
                    with st.popover("Reimprimir recibo", icon=":material/print:", use_container_width=True):
                        _reimprimir_recibo(ctx, venta, items_venta, pagos_venta)
                elif accion == "editar":
                    with st.popover("Editar datos", icon=":material/edit:", use_container_width=True):
                        _formulario_edicion(ctx, venta)
                elif accion == "anular":
                    with st.popover("Anular venta", icon=":material/cancel:", use_container_width=True):
                        _formulario_anulacion(ctx, venta)
                else:
                    with st.popover("Devolución / cambio", icon=":material/keyboard_return:", use_container_width=True):
                        _formulario_devolucion(ctx, venta, items_venta)


def _reimprimir_recibo(ctx: ViewContext, venta, items_venta, pagos_venta) -> None:
    datos = {campo: venta[campo] for campo in venta.index}
    datos["items"] = [dict(fila) for _, fila in items_venta.iterrows()]
    datos["pagos"] = [dict(fila) for _, fila in pagos_venta.iterrows()]
    try:
        pdf = generar_pdf_recibo(
            datos,
            nombre_negocio=ctx.storage.get_config("negocio_nombre") or "Ola Tata · Bolsos & Accesorios",
            mensaje=ctx.storage.get_config("negocio_mensaje_recibo") or "¡Gracias por tu compra!",
            vendedor=_texto(venta["vendedor_nombre"]) or None,
        )
    except Exception as exc:  # nunca una traza visible
        mensaje, _codigo = mensaje_error_amable(exc, contexto="reimprimir_recibo")
        st.error(mensaje)
        return
    boton_imprimir_pdf(pdf, "Imprimir recibo", nombre_archivo=f"recibo_{_texto(venta['numero'])}.pdf",
                       key=f"ventas_recibo_{venta['id']}")


def _formulario_edicion(ctx: ViewContext, venta) -> None:
    """Solo el maestro: datos de la venta que no cambian dinero ni stock."""
    st.caption(
        "Para cambiar productos, cantidades o montos usa «Anular venta» o «Devolución / cambio»: "
        "así la caja y el inventario siguen cuadrando."
    )

    def _v(campo):
        valor = venta.get(campo, "")
        return "" if pd.isna(valor) else str(valor)

    canales = sorted(CANALES_VENTA)
    with st.form(f"editar_venta_{venta['id']}"):
        cliente = st.text_input("Cliente", value=_v("cliente_nombre"))
        telefono = st.text_input("Teléfono del cliente", value=_v("cliente_telefono"))
        canal = st.selectbox(
            "Canal", canales, index=canales.index(_v("canal")) if _v("canal") in canales else 0,
            format_func=lambda c: {"tienda": "Tienda", "instagram": "Instagram", "whatsapp": "WhatsApp"}.get(c, c),
        )
        ciudad = st.text_input("Ciudad del envío", value=_v("envio_ciudad"))
        transportadora = st.text_input("Transportadora", value=_v("envio_transportadora"))
        guia_envio = st.text_input("Número de guía", value=_v("envio_guia"))
        nota = st.text_area("Nota", value=_v("nota"))
        guardar = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)
    if guardar:
        try:
            cambiados = editar_venta(
                ctx.storage, ctx.usuario.rol, ctx.usuario.id, venta["id"],
                {
                    "cliente_nombre": cliente, "cliente_telefono": telefono, "canal": canal,
                    "envio_ciudad": ciudad, "envio_transportadora": transportadora, "envio_guia": guia_envio,
                    "nota": nota,
                },
            )
        except (PermisoDenegadoError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:  # nunca una traza visible
            mensaje, _codigo = mensaje_error_amable(exc, contexto="editar_venta")
            st.error(mensaje)
        else:
            if cambiados:
                st.success("Venta actualizada. El cambio quedó en el registro de seguridad.")
                ctx.rerun()
            else:
                st.info("No había cambios.")


def _formulario_anulacion(ctx: ViewContext, venta) -> None:
    storage = ctx.storage
    usuario = ctx.usuario
    st.warning("Esta acción no se puede deshacer. La venta quedará marcada como anulada y se repondrá el stock.")
    motivo = st.text_area("Motivo de anulación (obligatorio)", key=f"motivo_anular_{venta['id']}")
    if st.button("Confirmar anulación", key=f"confirmar_anular_{venta['id']}"):
        try:
            anular_venta(storage, usuario.rol, venta["numero"], motivo, usuario_id=usuario.id)
        except PermisoDenegadoError:
            st.error("No tienes permiso para anular ventas. Código: VTA-PERM.")
        except DevolucionInvalidaError as exc:
            st.error(f"No se pudo anular: {exc} Código: VTA-002.")
        else:
            st.success("Venta anulada. El stock se repuso.")
            ctx.rerun()


def _formulario_devolucion(ctx: ViewContext, venta, items_venta) -> None:
    storage = ctx.storage
    usuario = ctx.usuario
    opciones_producto = {
        f"{row['nombre_snapshot']} ({int(row['cantidad'])} vendidas)": row["producto_id"]
        for _, row in items_venta.iterrows()
    }
    if not opciones_producto:
        st.info("Esta venta no tiene productos.")
        return
    etiqueta_producto = st.selectbox("Producto", list(opciones_producto.keys()), key=f"dev_producto_{venta['id']}")
    cantidad = st.number_input("Cantidad a devolver", min_value=1, value=1, key=f"dev_cantidad_{venta['id']}")
    tipo = st.selectbox("Tipo", ["devolucion", "cambio"], key=f"dev_tipo_{venta['id']}")
    destino = st.selectbox(
        "¿El producto vuelve a stock o está dañado (merma)?",
        ["stock", "merma"],
        key=f"dev_destino_{venta['id']}",
    )
    reembolso_metodo = st.selectbox(
        "Reembolso vía",
        list(_METODOS_LABEL.keys()),
        format_func=lambda k: _METODOS_LABEL[k],
        key=f"dev_reembolso_{venta['id']}",
    )
    motivo = st.text_area("Motivo (obligatorio)", key=f"dev_motivo_{venta['id']}")
    if st.button("Registrar devolución", key=f"dev_confirmar_{venta['id']}"):
        producto_id = opciones_producto[etiqueta_producto]
        try:
            dev = registrar_devolucion_cambio(
                storage,
                usuario.rol,
                venta["numero"],
                items_devueltos=[{"producto_id": producto_id, "cantidad": int(cantidad), "destino": destino}],
                tipo=tipo,
                motivo=motivo,
                reembolso_metodo=reembolso_metodo,
                usuario_id=usuario.id,
            )
        except PermisoDenegadoError:
            st.error("No tienes permiso para registrar devoluciones. Código: VTA-PERM2.")
        except (DevolucionInvalidaError, VentaNoEncontradaError) as exc:
            st.error(f"No se pudo registrar: {exc} Código: VTA-003.")
        else:
            st.success(f"Devolución {dev.numero} registrada por {format_cop(dev.reembolso_monto)}.")
            ctx.rerun()
