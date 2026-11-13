"""Vista: Ventas. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`.

Lista del día/rango, detalle, devolución/cambio (vendedor o admin) y
anulación (SOLO admin, con motivo obligatorio) -- §6.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from core import schema
from core.edicion_ventas import editar_venta
from core.money import format_cop
from core.permissions import PermisoDenegadoError, tiene_capacidad
from core.returns import DevolucionInvalidaError, VentaNoEncontradaError, anular_venta, registrar_devolucion_cambio
from core.schema import CANALES_VENTA
from core.timeutil import local_date, now_utc
from core.ui import (
    card,
    chip_estado,
    encabezado_pagina,
    estado_vacio,
    guia,
    md_seguro,
    mensaje_error_amable,
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

    with card(acento="superior"):
        col1, col2 = st.columns(2)
        # R2: "hoy" SIEMPRE en America/Bogota, nunca date.today() (hora
        # del servidor, típicamente UTC en despliegues cloud — §2.a).
        hoy = local_date(now_utc())
        desde = col1.date_input("Desde", value=hoy - timedelta(days=7), key="ventas_desde")
        hasta = col2.date_input("Hasta", value=hoy, key="ventas_hasta")

    ventas_df = storage.read_sheet(schema.VENTAS)
    if ventas_df.empty:
        estado_vacio("Todavía no se ha registrado ninguna venta.", icono="receipt_long")
        return

    ventas_df = ventas_df[
        (ventas_df["fecha_local"] >= desde.isoformat()) & (ventas_df["fecha_local"] <= hasta.isoformat())
    ]

    if not tiene_capacidad(usuario.rol, "ver_ventas_todas"):
        ventas_df = ventas_df[ventas_df["vendedor_id"] == usuario.id]

    if ventas_df.empty:
        estado_vacio("No hay ventas en ese rango de fechas.", icono="date_range")
        return

    ventas_df = ventas_df.sort_values("fecha_hora_utc", ascending=False)
    for _, venta in ventas_df.iterrows():
        _fila_venta(ctx, venta)


def _fila_venta(ctx: ViewContext, venta) -> None:
    storage = ctx.storage
    usuario = ctx.usuario
    anulada = venta["estado"] == "anulada"
    titulo = f"{venta['numero']} · {format_cop(int(venta['total']))} · {venta['fecha_local']}"
    with st.expander(titulo, icon=":material/cancel:" if anulada else ":material/check_circle:"):
        st.markdown(
            chip_estado("Anulada", "error") if anulada else chip_estado("Confirmada", "exito"),
            unsafe_allow_html=True,
        )
        st.markdown(f"Vendedor: {md_seguro(venta['vendedor_nombre'])}")
        st.markdown(f"Canal: {md_seguro(venta['canal'])}")
        def _hay(campo):
            valor = venta.get(campo, "")
            return "" if pd.isna(valor) else str(valor).strip()

        if _hay("cliente_nombre"):
            telefono = f" · {md_seguro(_hay('cliente_telefono'))}" if _hay("cliente_telefono") else ""
            st.markdown(f"Cliente: {md_seguro(_hay('cliente_nombre'))}{telefono}")
        envio = [x for x in (_hay("envio_ciudad"), _hay("envio_transportadora"), _hay("envio_guia")) if x]
        if envio:
            st.markdown("Envío: " + " · ".join(md_seguro(x) for x in envio))
        if _hay("nota"):
            st.markdown(f"Nota: {md_seguro(_hay('nota'))}")

        items_df = storage.read_sheet(schema.VENTA_ITEMS)
        items_venta = items_df[items_df["venta_id"] == venta["id"]]
        for _, item in items_venta.iterrows():
            st.markdown(
                f"{int(item['cantidad'])} x {md_seguro(item['nombre_snapshot'])} — {md_seguro(format_cop(int(item['total_linea'])))}"
            )

        if venta["estado"] == "anulada":
            st.error(f"Anulada. Motivo: {md_seguro(venta['anulada_motivo'])}")
            return

        puede_editar = tiene_capacidad(usuario.rol, "editar_venta")
        cols = st.columns(3 if puede_editar else 2)
        col1, col2 = cols[0], cols[1]
        if puede_editar:
            with cols[2].popover("Editar datos", icon=":material/edit:", use_container_width=True):
                _formulario_edicion(ctx, venta)

        if tiene_capacidad(usuario.rol, "anular_venta"):
            with col1.popover("Anular venta", icon=":material/cancel:", use_container_width=True):
                _formulario_anulacion(ctx, venta)

        if tiene_capacidad(usuario.rol, "devolucion_cambio"):
            with col2.popover("Devolución / cambio", icon=":material/keyboard_return:", use_container_width=True):
                _formulario_devolucion(ctx, venta, items_venta)


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
