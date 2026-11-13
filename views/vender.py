"""Vista: Vender. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`.

Meta medible (§6): venta simple en <=4 pasos y <30s (buscar/escanear ->
cantidad -> pagar -> confirmar).

Diseño: dos columnas. Izquierda: búsqueda EN TIEMPO REAL (`live`: los
resultados aparecen mientras se escribe, sin Enter) + carrito. Derecha:
resumen fijo (descuento, canal, cliente/envío, total, pago y Cobrar), para
casi no tener que desplazar la pantalla. El lector USB "teclea" el código
+ Enter: una coincidencia EXACTA por código se agrega sola y el campo se
limpia. El carrito vive en `st.session_state`.
"""
from __future__ import annotations

import uuid

import streamlit as st

from core import schema
from core.busqueda import buscar_productos, producto_por_codigo, stock_por_producto
from core.etiquetas import codigo_para_producto
from core.excel_safe import excel_safe
from core.money import format_cop, parse_pesos
from core.permissions import PermisoDenegadoError
from core.recibo_impreso import generar_pdf_recibo
from core.receipts import generar_texto_recibo, generar_url_whatsapp
from core.sales import PagoInvalidoError, StockInsuficienteError, VentaInvalidaError, confirmar_venta
from core.ui import (
    boton_imprimir_pdf,
    card,
    chip_estado,
    encabezado_pagina,
    enfocar_campo,
    estado_vacio,
    guia,
    md_seguro,
    mensaje_error_amable,
    render_logo,
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
def _cb_busqueda(productos_activos) -> None:
    """Al escribir/escanear: si es un CÓDIGO exacto, se agrega solo y se
    limpia el campo (flujo del lector USB). Si no, quedan los resultados."""
    texto = st.session_state.get("vender_q", "") or ""
    fila = producto_por_codigo(productos_activos, texto)
    if fila is None:
        return
    _cb_agregar_producto(fila)
    st.session_state["vender_q"] = ""


def _cb_agregar_producto(fila) -> None:
    _leer_widgets_al_estado()
    _agregar_al_carrito(fila)
    st.session_state["vender_ultimo"] = str(fila["nombre"])
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
    for clave in [k for k in st.session_state.keys() if str(k).startswith(("vender_v_", "vender_q", "vender_ultimo"))]:
        del st.session_state[clave]
    st.session_state.vender_carrito = []
    st.session_state.vender_idempotency_key = str(uuid.uuid4())
    st.session_state.vender_pagos = [{"metodo": "efectivo", "monto": 0}]
    st.session_state.vender_recibo = None


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

    if st.session_state.vender_recibo is not None:
        _mostrar_recibo(ctx)
        return

    encabezado_pagina("Vender", "Busca o escanea un producto para empezar", icono="shopping_bag")
    guia("vender")

    productos_df = storage.read_sheet(schema.PRODUCTOS)
    if productos_df.empty:
        estado_vacio(
            "Todavía no hay productos en el inventario.",
            "Agrega productos en la pantalla Inventario.",
            icono="inventory_2",
        )
        return
    productos_activos = productos_df[productos_df["activo"] == True]  # noqa: E712
    stock = stock_por_producto(storage.read_sheet(schema.STOCK))
    sin_stock_permitido = (storage.get_config("permitir_vender_sin_stock") or "false").strip().lower() == "true"

    col_izq, col_der = st.columns([7, 5], gap="large")
    with col_izq:
        _panel_busqueda(productos_activos, stock, sin_stock_permitido)
        _panel_carrito(ctx)
    with col_der:
        _panel_resumen(ctx)


def _panel_busqueda(productos_activos, stock: dict, sin_stock_permitido: bool) -> None:
    with card(acento="superior", key="ot-card-vender-buscar"):
        st.text_input(
            "Buscar por nombre, código o escanear",
            key="vender_q",
            live="250ms",
            placeholder="Escribe parte del nombre o el código… o escanea la etiqueta",
            icon=":material/search:",
            on_change=_cb_busqueda,
            args=(productos_activos,),
        )
        # El lector de códigos "teclea" + Enter: el cursor queda listo aquí
        # (sin mover la pantalla).
        enfocar_campo("Buscar por nombre, código o escanear")
        consulta = (st.session_state.get("vender_q") or "").strip()
        if not consulta:
            st.caption("Los resultados aparecen mientras escribes. Un código escaneado se agrega solo.")
            return
        resultados = buscar_productos(productos_activos, consulta)
        if resultados.empty:
            st.markdown(
                chip_estado("Ningún producto coincide con la búsqueda", "alerta", icono="search_off"),
                unsafe_allow_html=True,
            )
            return
        for _, fila in resultados.iterrows():
            pid = str(fila["id"])
            disponible = int(stock.get(pid, 0))
            c1, c2, c3 = st.columns([5, 3, 2], vertical_alignment="center")
            c1.markdown(
                f"**{md_seguro(fila['nombre'])}**  \n"
                f"<span class='ot-resultado__codigo'>{md_seguro(codigo_para_producto(pid, fila.get('codigo_barras')))}"
                f" · {md_seguro(fila.get('categoria') or '')}</span>",
                unsafe_allow_html=True,
            )
            precio = format_cop(parse_pesos(fila["precio"]))
            estado = (
                chip_estado(f"{disponible} disp.", "exito", icono="inventory_2") if disponible > 0
                else chip_estado("Agotado", "error", icono="block")
            )
            c2.markdown(f'<span class="ot-precio-producto">{precio}</span><br>{estado}', unsafe_allow_html=True)
            c3.button(
                "Agregar",
                key=f"vender_add_{pid}",
                icon=":material/add_shopping_cart:",
                type="primary",
                use_container_width=True,
                disabled=disponible <= 0 and not sin_stock_permitido,
                on_click=_cb_agregar_producto,
                args=(fila,),
            )


def _panel_carrito(ctx: ViewContext) -> None:
    carrito = st.session_state.vender_carrito
    unidades = sum(int(linea["cantidad"]) for linea in carrito)
    with card(acento="izquierdo", key="ot-card-vender-carrito"):
        titulo_seccion(f"Carrito · {unidades} {'unidad' if unidades == 1 else 'unidades'}" if carrito else "Carrito")
        if not carrito:
            st.caption("Vacío. Busca o escanea un producto para empezar.")
            return
        ultimo = st.session_state.get("vender_ultimo")
        if ultimo:
            st.markdown(chip_estado(f"Agregado: {md_seguro(ultimo)}", "exito"), unsafe_allow_html=True)
        for idx, linea in enumerate(carrito):
            col1, col2, col3, col4 = st.columns([4.2, 2.2, 2.4, 1], vertical_alignment="center")
            col1.markdown(
                f"**{md_seguro(linea['nombre_snapshot'])}**  \n"
                f"<span class='ot-resultado__codigo'>{md_seguro(format_cop(linea['precio_unitario']))} c/u</span>",
                unsafe_allow_html=True,
            )
            clave_cant = f"vender_cant_{idx}"
            # `value=` solo si el widget aún no tiene estado: si se fijó
            # desde un callback, pasarlo también genera un aviso de Streamlit.
            inicial = {} if clave_cant in st.session_state else {"value": int(linea["cantidad"])}
            nueva_cantidad = col2.number_input(
                "Cant.", min_value=1, key=clave_cant, step=1, label_visibility="collapsed", **inicial
            )
            linea["cantidad"] = int(nueva_cantidad)
            col3.markdown(
                f'<span class="ot-precio-producto">{format_cop(linea["precio_unitario"] * linea["cantidad"])}</span>',
                unsafe_allow_html=True,
            )
            col4.button(
                "",
                key=f"vender_del_{idx}",
                icon=":material/delete:",
                help="Quitar del carrito",
                on_click=_cb_quitar_linea,
                args=(idx,),
                use_container_width=True,
            )


def _panel_resumen(ctx: ViewContext) -> None:
    storage = ctx.storage
    usuario = ctx.usuario
    carrito = st.session_state.vender_carrito
    with card(acento="superior", key="ot-card-venta-resumen"):
        titulo_seccion("Resumen")
        if not carrito:
            st.caption("Agrega productos para ver el total y cobrar.")
            st.markdown(
                '<div class="ot-total-carrito"><div class="ot-total-carrito__etiqueta">Total</div>'
                f'<div class="ot-total-carrito__valor">{format_cop(0)}</div></div>',
                unsafe_allow_html=True,
            )
            return

        subtotal = sum(linea["precio_unitario"] * linea["cantidad"] for linea in carrito)
        col_desc1, col_desc2 = st.columns(2)
        tipo_descuento = col_desc1.selectbox(
            "Descuento", ["Sin descuento", "Porcentaje (%)", "Monto ($)"], key="vender_v_desc_tipo"
        )
        valor_descuento = col_desc2.number_input(
            "Valor", min_value=0, value=0, key="vender_v_desc_valor",
            disabled=tipo_descuento == "Sin descuento",
        )
        canal = st.selectbox(
            "Canal", list(_CANALES_LABEL.keys()), format_func=lambda k: _CANALES_LABEL[k], key="vender_v_canal"
        )
        with st.expander("Cliente y envío (opcional)", icon=":material/person:", key="vender_v_exp_cliente"):
            cliente_nombre = st.text_input("Nombre del cliente", key="vender_v_cliente")
            cliente_telefono = st.text_input("Teléfono del cliente", key="vender_v_telefono")
            envio_cobrado = st.number_input("Valor cobrado por el envío", min_value=0, value=0, key="vender_v_envio")
            envio_ciudad = st.text_input("Ciudad destino", key="vender_v_ciudad")
            envio_transportadora = st.text_input("Transportadora", key="vender_v_transportadora")
            envio_guia = st.text_input("Número de guía", key="vender_v_guia")

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

        detalle = f"Subtotal {format_cop(subtotal)}"
        if descuento_pesos:
            detalle += f" · Descuento −{format_cop(descuento_pesos)}"
        if envio_cobrado:
            detalle += f" · Envío {format_cop(int(envio_cobrado))}"
        st.markdown(
            '<div class="ot-total-carrito">'
            '<div class="ot-total-carrito__etiqueta">Total</div>'
            f'<div class="ot-total-carrito__valor">{format_cop(total_estimado)}</div>'
            f'<div class="ot-total-carrito__detalle">{detalle}</div>'
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("**Pago**")
        for idx, pago in enumerate(st.session_state.vender_pagos):
            colm, colv, colx = st.columns([5, 5, 2], vertical_alignment="bottom")
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
            pago["monto"] = colv.number_input("Monto", min_value=0, step=1000, key=clave_monto, **inicial_monto)
            if len(st.session_state.vender_pagos) > 1:
                colx.button(
                    "", key=f"vender_pago_del_{idx}", icon=":material/delete:", help="Quitar este método",
                    on_click=_cb_quitar_pago, args=(idx,), use_container_width=True,
                )

        colb1, colb2 = st.columns(2)
        colb1.button(
            "Otro método", icon=":material/add:", use_container_width=True, on_click=_cb_agregar_pago,
            help="Dividir el pago entre dos o más métodos",
        )
        colb2.button(
            "Completar",
            icon=":material/payments:",
            use_container_width=True,
            help="Llena el último monto con lo que falta para completar el total",
            on_click=_cb_completar_total,
            args=(total_estimado,),
        )

        suma_pagos = sum(int(p["monto"]) for p in st.session_state.vender_pagos)
        diferencia = total_estimado - suma_pagos
        # Indicador de ALTURA FIJA: antes un aviso aparecía/desaparecía y la
        # pantalla "saltaba" al completar el pago.
        if diferencia == 0:
            estado_pago = chip_estado("Pago completo", "exito", icono="check_circle")
        elif diferencia > 0:
            estado_pago = chip_estado(f"Falta {format_cop(diferencia)}", "alerta", icono="pending")
        else:
            estado_pago = chip_estado(f"Sobra {format_cop(-diferencia)}: revisa los montos", "error")
        st.markdown(f'<div class="ot-estado-pago">{estado_pago}</div>', unsafe_allow_html=True)

        cobrar = st.button(
            "Cobrar",
            type="primary",
            use_container_width=True,
            icon=":material/point_of_sale:",
            disabled=(diferencia != 0),
            key="vender_cobrar",
        )
    if not cobrar:
        return
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
                for l in carrito
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
        st.error(f"No hay suficiente stock de '{exc.producto_id}' (disponible: {exc.disponible}). Código: VEN-STOCK.")
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
    try:
        pdf_recibo = generar_pdf_recibo(
            venta,
            nombre_negocio=ctx.storage.get_config("negocio_nombre") or "Ola Tata · Bolsos & Accesorios",
            mensaje=ctx.storage.get_config("negocio_mensaje_recibo") or "¡Gracias por tu compra!",
            vendedor=getattr(ctx.usuario, "nombre", None),
        )
    except Exception as exc:  # imprimir nunca debe tumbar la venta ya guardada
        mensaje_error, _codigo = mensaje_error_amable(exc, contexto="recibo_pdf")
        st.warning(mensaje_error)
    else:
        boton_imprimir_pdf(
            pdf_recibo, "Imprimir recibo", nombre_archivo=f"recibo_{venta.numero}.pdf", key="vender_recibo_pdf"
        )
    telefono = ctx.storage.get_config("telefono_whatsapp")
    url_whatsapp = generar_url_whatsapp(venta, telefono_whatsapp=telefono)
    st.link_button(
        "Enviar por WhatsApp", url_whatsapp, use_container_width=True, icon=":material/chat:"
    )
    if st.button("Nueva venta", type="primary", use_container_width=True, icon=":material/add_shopping_cart:"):
        _nueva_venta()
        ctx.rerun()
