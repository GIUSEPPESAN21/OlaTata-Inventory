"""Vista: Vender. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`.

Meta medible (§6): venta simple en <=4 pasos y <30s (buscar/escanear ->
cantidad -> pagar -> confirmar). Patrón de escáner USB sano: `st.form`
con `text_input` + `clear_on_submit=True`, Enter agrega al carrito si
hay coincidencia exacta -- SIN JavaScript inyectado ni listeners de
teclado frágiles. El carrito vive en `st.session_state` para sobrevivir
a un F5 mientras la pestaña siga abierta.
"""
from __future__ import annotations

import uuid

import streamlit as st

from core import schema
from core.excel_safe import excel_safe
from core.money import format_cop, parse_pesos
from core.permissions import PermisoDenegadoError
from core.receipts import generar_texto_recibo, generar_url_whatsapp
from core.sales import PagoInvalidoError, StockInsuficienteError, VentaInvalidaError, confirmar_venta
from core.ui import card, chip_estado, encabezado_pagina, estado_vacio, render_logo, titulo_seccion
from views import ViewContext

_METODOS_LABEL = {
    "efectivo": "Efectivo",
    "datafono": "Datáfono",
    "transferencia": "Transferencia",
    "sistecredito": "Sistecrédito",
    "cambio": "Cambio (saldo a favor)",
}
_CANALES_LABEL = {"tienda": "Tienda", "instagram": "Instagram", "whatsapp": "WhatsApp"}


def _init_state() -> None:
    st.session_state.setdefault("vender_carrito", [])
    st.session_state.setdefault("vender_idempotency_key", str(uuid.uuid4()))
    st.session_state.setdefault("vender_pagos", [{"metodo": "efectivo", "monto": 0}])
    st.session_state.setdefault("vender_recibo", None)


def _nueva_venta() -> None:
    st.session_state.vender_carrito = []
    st.session_state.vender_idempotency_key = str(uuid.uuid4())
    st.session_state.vender_pagos = [{"metodo": "efectivo", "monto": 0}]
    st.session_state.vender_recibo = None


def _buscar_producto(productos_df, texto: str):
    texto = texto.strip()
    if not texto:
        return None
    por_codigo = productos_df[productos_df["codigo_barras"].astype(str) == texto]
    if not por_codigo.empty:
        return por_codigo.iloc[0]
    por_id = productos_df[productos_df["id"].astype(str) == texto]
    if not por_id.empty:
        return por_id.iloc[0]
    por_nombre = productos_df[productos_df["nombre"].astype(str).str.lower() == texto.lower()]
    if not por_nombre.empty:
        return por_nombre.iloc[0]
    return None


def _agregar_al_carrito(fila) -> None:
    producto_id = str(fila["id"])
    for linea in st.session_state.vender_carrito:
        if linea["producto_id"] == producto_id:
            linea["cantidad"] += 1
            return
    st.session_state.vender_carrito.append(
        {
            "producto_id": producto_id,
            "nombre_snapshot": excel_safe(str(fila["nombre"]), field_name="nombre_snapshot"),
            "cantidad": 1,
            "precio_unitario": parse_pesos(fila["precio"]),
            "costo_unitario": parse_pesos(fila["costo"]),
        }
    )


def render(ctx: ViewContext) -> None:
    _init_state()
    storage = ctx.storage
    usuario = ctx.usuario

    if st.session_state.vender_recibo is not None:
        _mostrar_recibo(ctx)
        return

    encabezado_pagina("Vender", "Busca o escanea un producto para empezar", icono="shopping_bag")

    productos_df = storage.read_sheet(schema.PRODUCTOS)
    if productos_df.empty:
        estado_vacio(
            "Todavía no hay productos en el inventario.",
            "Agrega productos en la pantalla Inventario.",
            icono="inventory_2",
        )
        return
    productos_activos = productos_df[productos_df["activo"] == True]  # noqa: E712

    with card(acento="superior"):
        with st.form("vender_buscar", clear_on_submit=True):
            texto_busqueda = st.text_input("Buscar por nombre, código o escanear", icon=":material/search:")
            buscar = st.form_submit_button(
                "Agregar al carrito", use_container_width=True, type="primary", icon=":material/add_shopping_cart:"
            )
    if buscar:
        fila = _buscar_producto(productos_activos, texto_busqueda)
        if fila is None:
            st.error("No se encontró ningún producto con ese nombre/código. Código: VEN-404.")
        else:
            _agregar_al_carrito(fila)
            ctx.rerun()

    if not st.session_state.vender_carrito:
        estado_vacio("El carrito está vacío.", "Busca o escanea un producto para empezar.", icono="shopping_cart")
        return

    with card(acento="izquierdo"):
        titulo_seccion("Carrito", centrado=False)
        idx_a_eliminar = None
        for idx, linea in enumerate(st.session_state.vender_carrito):
            col1, col2, col3, col4 = st.columns([3.2, 1.6, 1.6, 1.6])
            col1.write(linea["nombre_snapshot"])
            nueva_cantidad = col2.number_input(
                "Cant.", min_value=1, value=int(linea["cantidad"]), key=f"vender_cant_{idx}", step=1
            )
            linea["cantidad"] = int(nueva_cantidad)
            col3.markdown(
                f'<span class="ot-precio-producto">{format_cop(linea["precio_unitario"] * linea["cantidad"])}</span>',
                unsafe_allow_html=True,
            )
            if col4.button("Quitar", key=f"vender_del_{idx}", icon=":material/delete:", help="Quitar del carrito"):
                idx_a_eliminar = idx
        if idx_a_eliminar is not None:
            st.session_state.vender_carrito.pop(idx_a_eliminar)
            ctx.rerun()

        subtotal = sum(l["precio_unitario"] * l["cantidad"] for l in st.session_state.vender_carrito)
        st.caption(f"Subtotal: {format_cop(subtotal)}")

        col_desc1, col_desc2 = st.columns(2)
        tipo_descuento = col_desc1.selectbox("Descuento", ["Sin descuento", "Porcentaje (%)", "Monto ($)"])
        valor_descuento = 0
        if tipo_descuento != "Sin descuento":
            valor_descuento = col_desc2.number_input("Valor del descuento", min_value=0, value=0)

        canal = st.selectbox("Canal", list(_CANALES_LABEL.keys()), format_func=lambda k: _CANALES_LABEL[k])

        with st.expander("Cliente (opcional)"):
            cliente_nombre = st.text_input("Nombre del cliente", icon=":material/person:")
            cliente_telefono = st.text_input("Teléfono del cliente", icon=":material/call:")

        with st.expander("Envío nacional (opcional)"):
            envio_cobrado = st.number_input("Valor cobrado por el envío", min_value=0, value=0)
            envio_ciudad = st.text_input("Ciudad destino")
            envio_transportadora = st.text_input("Transportadora")
            envio_guia = st.text_input("Número de guía")

    if tipo_descuento == "Porcentaje (%)":
        descuento_dict = {"tipo": "porcentaje", "valor": valor_descuento}
        descuento_pesos = min(subtotal, round(subtotal * valor_descuento / 100))
    elif tipo_descuento == "Monto ($)":
        descuento_dict = {"tipo": "monto", "valor": valor_descuento}
        descuento_pesos = min(subtotal, int(valor_descuento))
    else:
        descuento_dict = None
        descuento_pesos = 0

    total_estimado = subtotal - descuento_pesos + int(envio_cobrado)

    st.markdown(
        f"""
        <div class="ot-total-carrito">
            <div class="ot-total-carrito__etiqueta">Total</div>
            <div class="ot-total-carrito__valor">{format_cop(total_estimado)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with card(acento="izquierdo"):
        titulo_seccion("Pago", centrado=False)
        st.caption("Puedes dividir el pago en dos o más métodos.")
        idx_pago_eliminar = None
        for idx, pago in enumerate(st.session_state.vender_pagos):
            colm, colv, colx = st.columns([2, 2, 1])
            metodos = list(_METODOS_LABEL.keys())
            pago["metodo"] = colm.selectbox(
                "Método",
                metodos,
                index=metodos.index(pago["metodo"]) if pago["metodo"] in metodos else 0,
                format_func=lambda k: _METODOS_LABEL[k],
                key=f"vender_pago_metodo_{idx}",
            )
            pago["monto"] = colv.number_input(
                "Monto", min_value=0, value=int(pago["monto"]), key=f"vender_pago_monto_{idx}"
            )
            if len(st.session_state.vender_pagos) > 1 and colx.button(
                "Quitar", key=f"vender_pago_del_{idx}", icon=":material/delete:"
            ):
                idx_pago_eliminar = idx
        if idx_pago_eliminar is not None:
            st.session_state.vender_pagos.pop(idx_pago_eliminar)
            ctx.rerun()

        colb1, colb2 = st.columns(2)
        if colb1.button("Agregar método de pago", icon=":material/add:", use_container_width=True):
            st.session_state.vender_pagos.append({"metodo": "efectivo", "monto": 0})
            ctx.rerun()
        if colb2.button("Completar con el total restante", icon=":material/payments:", use_container_width=True):
            suma_otros = sum(p["monto"] for p in st.session_state.vender_pagos[:-1])
            st.session_state.vender_pagos[-1]["monto"] = max(0, total_estimado - suma_otros)
            ctx.rerun()

        suma_pagos = sum(int(p["monto"]) for p in st.session_state.vender_pagos)
        # Dos columnas en vez de un solo st.write con dos montos: Streamlit
        # interpreta "$...$" como LaTeX inline, y dos montos formateados con
        # "$ " en el mismo texto (R1) abren/cierran un bloque matemático sin
        # querer, mostrando "**" literales en vez de negrita (capa visual).
        col_total, col_pagado = st.columns(2)
        col_total.markdown(f"Total: **{format_cop(total_estimado)}**")
        col_pagado.markdown(f"Pagado: **{format_cop(suma_pagos)}**")
        if suma_pagos != total_estimado:
            st.warning("La suma de los pagos debe ser exactamente igual al total.")

    if st.button(
        "Cobrar",
        type="primary",
        use_container_width=True,
        icon=":material/point_of_sale:",
        disabled=(suma_pagos != total_estimado),
    ):
        try:
            venta = confirmar_venta(
                storage,
                usuario.rol,
                st.session_state.vender_idempotency_key,
                items=[
                    {
                        "producto_id": l["producto_id"],
                        "cantidad": l["cantidad"],
                        "precio_unitario": l["precio_unitario"],
                        "costo_unitario": l["costo_unitario"],
                        "nombre_snapshot": l["nombre_snapshot"],
                    }
                    for l in st.session_state.vender_carrito
                ],
                pagos=[{"metodo": p["metodo"], "monto": int(p["monto"])} for p in st.session_state.vender_pagos],
                descuento=descuento_dict,
                envio={
                    "cobrado": int(envio_cobrado),
                    "ciudad": envio_ciudad,
                    "transportadora": envio_transportadora,
                    "guia": envio_guia,
                },
                canal=canal,
                cliente={"nombre": cliente_nombre, "telefono": cliente_telefono},
                vendedor_id=usuario.id,
                vendedor_nombre=usuario.nombre,
            )
        except StockInsuficienteError as exc:
            st.error(
                f"No hay suficiente stock de '{exc.producto_id}' (disponible: {exc.disponible}). Código: VEN-STOCK."
            )
        except PagoInvalidoError:
            st.error("La suma de los pagos no coincide con el total. Código: VEN-PAGO.")
        except (VentaInvalidaError, PermisoDenegadoError) as exc:
            st.error(f"No se pudo confirmar la venta: {exc} Código: VEN-001.")
        else:
            st.session_state.vender_recibo = venta
            ctx.rerun()


def _mostrar_recibo(ctx: ViewContext) -> None:
    venta = st.session_state.vender_recibo
    encabezado_pagina("Venta confirmada", icono="task_alt")
    st.markdown(chip_estado(f"Venta {venta.numero}", "exito"), unsafe_allow_html=True)
    estado_sync = ctx.storage.sync_status()
    if estado_sync.pendientes > 0:
        st.warning(
            "La venta quedó guardada de forma segura, pero todavía no se publicó en la nube. "
            "Se reintentará automáticamente."
        )
    with card(acento="ninguno", key="ot-card-recibo"):
        render_logo(72, nombre_archivo="olatata-logo-mono.png")
        st.code(generar_texto_recibo(venta), language=None)
    telefono = ctx.storage.get_config("telefono_whatsapp")
    url_whatsapp = generar_url_whatsapp(venta, telefono_whatsapp=telefono)
    st.link_button(
        "Enviar por WhatsApp", url_whatsapp, use_container_width=True, icon=":material/chat:"
    )
    if st.button("Nueva venta", type="primary", use_container_width=True, icon=":material/add_shopping_cart:"):
        _nueva_venta()
        ctx.rerun()
