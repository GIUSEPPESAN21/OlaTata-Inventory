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


_PREFIJOS_WIDGETS_CARRITO = ("vender_cant_", "vender_pago_metodo_", "vender_pago_monto_")


def _reiniciar_widgets_carrito() -> None:
    """Olvida el estado de los widgets de cantidad/pago (p.ej. al empezar
    una venta nueva, cuando esos widgets no están en pantalla)."""
    for clave in [k for k in st.session_state.keys() if str(k).startswith(_PREFIJOS_WIDGETS_CARRITO)]:
        del st.session_state[clave]


def _leer_widgets_al_estado() -> None:
    """Copia a `vender_carrito`/`vender_pagos` lo último que el usuario
    escribió en los widgets (por si cambió algo justo antes del clic)."""
    for idx, linea in enumerate(st.session_state.vender_carrito):
        valor = st.session_state.get(f"vender_cant_{idx}")
        if valor is not None:
            linea["cantidad"] = int(valor)
    for idx, pago in enumerate(st.session_state.vender_pagos):
        metodo = st.session_state.get(f"vender_pago_metodo_{idx}")
        monto = st.session_state.get(f"vender_pago_monto_{idx}")
        if metodo is not None:
            pago["metodo"] = metodo
        if monto is not None:
            pago["monto"] = int(monto)


def _escribir_estado_a_widgets() -> None:
    """Fija el valor de cada widget de cantidad/pago desde el estado real.

    Streamlit IGNORA el `value=` de un widget con `key` que ya tiene
    estado, y `st.rerun()` vuelve a aplicar lo que mandó el navegador.
    Por eso, cuando el CÓDIGO cambia el carrito o los pagos (escanear otra
    vez el mismo producto, quitar una línea, "Completar con el total
    restante"), el widget mostraba el valor viejo y lo escribía encima:
    el escáner no sumaba y "Completar" dejaba el pago en $ 0 (hallazgo de
    la prueba E2E). La forma soportada es fijar `st.session_state[key]`
    DENTRO de un callback `on_click` — que es desde donde se llama esto."""
    n_lineas = len(st.session_state.vender_carrito)
    n_pagos = len(st.session_state.vender_pagos)
    for clave in [k for k in st.session_state.keys() if str(k).startswith(_PREFIJOS_WIDGETS_CARRITO)]:
        idx = int(str(clave).rsplit("_", 1)[1])
        limite = n_lineas if str(clave).startswith("vender_cant_") else n_pagos
        if idx >= limite:
            del st.session_state[clave]
    for idx, linea in enumerate(st.session_state.vender_carrito):
        st.session_state[f"vender_cant_{idx}"] = int(linea["cantidad"])
    for idx, pago in enumerate(st.session_state.vender_pagos):
        st.session_state[f"vender_pago_metodo_{idx}"] = pago["metodo"]
        st.session_state[f"vender_pago_monto_{idx}"] = int(pago["monto"])


# ------------------------------------------------------------ callbacks
def _cb_agregar(productos_activos) -> None:
    _leer_widgets_al_estado()
    texto = st.session_state.get("vender_busqueda_texto", "") or ""
    fila = _buscar_producto(productos_activos, texto)
    if fila is None:
        st.session_state["vender_busqueda_error"] = True
        return
    st.session_state["vender_busqueda_error"] = False
    _agregar_al_carrito(fila)
    _escribir_estado_a_widgets()


def _cb_quitar_linea(idx: int) -> None:
    _leer_widgets_al_estado()
    st.session_state.vender_carrito.pop(idx)
    _escribir_estado_a_widgets()


def _cb_quitar_pago(idx: int) -> None:
    _leer_widgets_al_estado()
    st.session_state.vender_pagos.pop(idx)
    _escribir_estado_a_widgets()


def _cb_agregar_pago() -> None:
    _leer_widgets_al_estado()
    st.session_state.vender_pagos.append({"metodo": "efectivo", "monto": 0})
    _escribir_estado_a_widgets()


def _cb_completar_total(total_estimado: int) -> None:
    _leer_widgets_al_estado()
    pagos = st.session_state.vender_pagos
    suma_otros = sum(int(p["monto"]) for p in pagos[:-1])
    pagos[-1]["monto"] = max(0, int(total_estimado) - suma_otros)
    _escribir_estado_a_widgets()


def _nueva_venta() -> None:
    _reiniciar_widgets_carrito()
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
            st.text_input(
                "Buscar por nombre, código o escanear", icon=":material/search:", key="vender_busqueda_texto"
            )
            st.form_submit_button(
                "Agregar al carrito",
                use_container_width=True,
                type="primary",
                icon=":material/add_shopping_cart:",
                on_click=_cb_agregar,
                args=(productos_activos,),
            )
    if st.session_state.pop("vender_busqueda_error", False):
        st.error("No se encontró ningún producto con ese nombre/código. Código: VEN-404.")

    if not st.session_state.vender_carrito:
        estado_vacio("El carrito está vacío.", "Busca o escanea un producto para empezar.", icono="shopping_cart")
        return

    with card(acento="izquierdo"):
        titulo_seccion("Carrito", centrado=False)
        for idx, linea in enumerate(st.session_state.vender_carrito):
            col1, col2, col3, col4 = st.columns([3.2, 1.6, 1.6, 1.6])
            col1.write(linea["nombre_snapshot"])
            clave_cant = f"vender_cant_{idx}"
            # `value=` solo si el widget aún no tiene estado: si se fijó
            # desde un callback, pasarlo también genera un aviso de Streamlit.
            inicial = {} if clave_cant in st.session_state else {"value": int(linea["cantidad"])}
            nueva_cantidad = col2.number_input("Cant.", min_value=1, key=clave_cant, step=1, **inicial)
            linea["cantidad"] = int(nueva_cantidad)
            col3.markdown(
                f'<span class="ot-precio-producto">{format_cop(linea["precio_unitario"] * linea["cantidad"])}</span>',
                unsafe_allow_html=True,
            )
            col4.button(
                "Quitar",
                key=f"vender_del_{idx}",
                icon=":material/delete:",
                help="Quitar del carrito",
                on_click=_cb_quitar_linea,
                args=(idx,),
            )
        if not st.session_state.vender_carrito:  # se quitó la última línea
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
        for idx, pago in enumerate(st.session_state.vender_pagos):
            colm, colv, colx = st.columns([2, 2, 1])
            metodos = list(_METODOS_LABEL.keys())
            clave_metodo = f"vender_pago_metodo_{idx}"
            clave_monto = f"vender_pago_monto_{idx}"
            inicial_metodo = (
                {} if clave_metodo in st.session_state
                else {"index": metodos.index(pago["metodo"]) if pago["metodo"] in metodos else 0}
            )
            inicial_monto = {} if clave_monto in st.session_state else {"value": int(pago["monto"])}
            pago["metodo"] = colm.selectbox(
                "Método", metodos, format_func=lambda k: _METODOS_LABEL[k], key=clave_metodo, **inicial_metodo
            )
            pago["monto"] = colv.number_input("Monto", min_value=0, key=clave_monto, **inicial_monto)
            if len(st.session_state.vender_pagos) > 1:
                colx.button(
                    "Quitar",
                    key=f"vender_pago_del_{idx}",
                    icon=":material/delete:",
                    on_click=_cb_quitar_pago,
                    args=(idx,),
                )

        colb1, colb2 = st.columns(2)
        colb1.button(
            "Agregar método de pago", icon=":material/add:", use_container_width=True, on_click=_cb_agregar_pago
        )
        colb2.button(
            "Completar con el total restante",
            icon=":material/payments:",
            use_container_width=True,
            on_click=_cb_completar_total,
            args=(total_estimado,),
        )

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
    # Solo aplica con la base en la nube activa: en modo local `pendientes`
    # cuenta cada guardado y el aviso salía siempre (falso positivo).
    if getattr(ctx.storage, "sync_enabled", False) and estado_sync.pendientes > 0:
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
