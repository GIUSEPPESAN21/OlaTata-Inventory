"""Vista: Ventas. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`.

Lista del día/rango, detalle, devolución/cambio (vendedor o admin) y
anulación (SOLO admin, con motivo obligatorio) -- §6.
"""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from core import schema
from core.money import format_cop
from core.permissions import PermisoDenegadoError, tiene_capacidad
from core.returns import DevolucionInvalidaError, VentaNoEncontradaError, anular_venta, registrar_devolucion_cambio
from core.timeutil import local_date, now_utc
from core.ui import card, chip_estado, encabezado_pagina, estado_vacio
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
        st.write(f"Vendedor: {venta['vendedor_nombre']}")
        st.write(f"Canal: {venta['canal']}")
        if venta["cliente_nombre"]:
            st.write(f"Cliente: {venta['cliente_nombre']}")

        items_df = storage.read_sheet(schema.VENTA_ITEMS)
        items_venta = items_df[items_df["venta_id"] == venta["id"]]
        for _, item in items_venta.iterrows():
            st.write(f"{int(item['cantidad'])} x {item['nombre_snapshot']} — {format_cop(int(item['total_linea']))}")

        if venta["estado"] == "anulada":
            st.error(f"Anulada. Motivo: {venta['anulada_motivo']}")
            return

        col1, col2 = st.columns(2)

        if tiene_capacidad(usuario.rol, "anular_venta"):
            with col1.popover("Anular venta", icon=":material/cancel:", use_container_width=True):
                _formulario_anulacion(ctx, venta)

        if tiene_capacidad(usuario.rol, "devolucion_cambio"):
            with col2.popover("Devolución / cambio", icon=":material/keyboard_return:", use_container_width=True):
                _formulario_devolucion(ctx, venta, items_venta)


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
