"""Vista: Análisis. Propiedad de A3 (ANÁLISIS). Contrato: `render(ctx)`.

Pestañas Hoy / Semana / Mes / Meses anteriores (§7). El vendedor
(capacidad "ver_analisis_basico" sin "ver_analisis_completo") ve una
vista reducida: solo ventas/unidades/tickets de SU turno, sin costos ni
ganancia — la función de `core.analytics` ya omite esas claves del
resultado, esta vista simplemente no intenta mostrarlas.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import PALETA_MARCA, kpis_hoy, kpis_mes, kpis_mes_cerrado, kpis_semana
from core.cash_close import registrar_cuadre_caja
from core.excel_report import exportar_periodo_excel
from core.money import format_cop
from core.permissions import PermisoDenegadoError, tiene_capacidad
from core.timeutil import now_utc, local_date
from core.ui import (
    barras_ranking,
    card,
    encabezado_pagina,
    estado_vacio,
    guia,
    kpi_card,
    tabla_html,
    titulo_seccion,
)
from views import ViewContext

_COLOR_PRIMARIO = PALETA_MARCA[0]
_COLOR_DORADO = PALETA_MARCA[1]


def render(ctx: ViewContext) -> None:
    usuario = ctx.usuario
    rol = usuario.rol
    try:
        tiene_completo = tiene_capacidad(rol, "ver_analisis_completo")
    except Exception:
        tiene_completo = False

    hoy_local = local_date(now_utc())
    usuario_id = None if tiene_completo else usuario.id

    encabezado_pagina("Análisis", "Ventas, ganancias e inventario en cifras", icono="bar_chart")
    guia("analisis")
    if not tiene_completo:
        st.caption("Vista de vendedor: ventas, unidades y tickets de tu turno. Sin costos ni ganancia.")

    tab_hoy, tab_semana, tab_mes, tab_anteriores = st.tabs(
        ["Hoy", "Semana", "Mes", "Meses anteriores"], key="analisis_pestana", on_change="rerun"
    )

    # Solo se calcula la pestaña visible (antes se calculaban las 4 en cada clic).
    with tab_hoy:
        if tab_hoy.open:
            _render_hoy(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_semana:
        if tab_semana.open:
            _render_semana(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_mes:
        if tab_mes.open:
            _render_mes(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_anteriores:
        if tab_anteriores.open:
            _render_meses_anteriores(ctx, hoy_local, rol)


def _kpi_row(kpis: dict, tiene_completo: bool) -> None:
    columnas = st.columns(4 if not tiene_completo else 6)
    with columnas[0]:
        kpi_card("Ventas netas", format_cop(kpis["ventas_netas"]), icono="payments")
    with columnas[1]:
        kpi_card("Tickets", str(kpis["tickets"]), icono="receipt_long")
    with columnas[2]:
        kpi_card("Unidades", str(kpis["unidades"]), icono="inventory_2")
    with columnas[3]:
        kpi_card("Ticket promedio", kpis["ticket_promedio_fmt"], icono="request_quote")
    if tiene_completo:
        with columnas[4]:
            kpi_card("Ganancia", format_cop(kpis["ganancia"]), icono="savings")
        with columnas[5]:
            kpi_card("Margen", kpis["margen_pct"], icono="percent")


def _grafica_barras(barras: list[dict], titulo: str) -> go.Figure:
    df = pd.DataFrame(barras)
    fig = go.Figure(
        go.Bar(
            x=df["fecha"],
            y=df["ventas_netas"],
            marker_color=_COLOR_PRIMARIO,
            text=[format_cop(v) for v in df["ventas_netas"]],
            textposition="outside",
        )
    )
    # `titulo` no se pasa a `fig.update_layout` (hallazgo de V4): el
    # encabezado de sección (`titulo_seccion`) ya lo muestra arriba de la
    # tarjeta — repetirlo dentro del propio gráfico era redundante.
    fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f", showlegend=False)
    return fig


def _grafica_top(registros: list[dict], campo_y: str, etiqueta: str, titulo: str) -> go.Figure:
    df = pd.DataFrame(registros)
    if df.empty:
        return go.Figure()
    fig = go.Figure(
        go.Bar(
            x=df["nombre_snapshot"],
            y=df[campo_y],
            marker_color=_COLOR_DORADO,
            text=[format_cop(v) if etiqueta == "dinero" else str(v) for v in df[campo_y]],
            textposition="outside",
        )
    )
    fig.update_layout(showlegend=False)
    if etiqueta == "dinero":
        fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f")
    return fig


# --------------------------------------------------- estados vacíos (V4)
# Hallazgo de V4 (revisor UX, marcado como bloqueante para producción):
# sin ventas, `st.dataframe`/`st.plotly_chart` pintan su placeholder
# nativo ("empty" en inglés, o un lienzo completamente en blanco) en vez
# de un estado vacío propio — exactamente el escenario de un negocio
# nuevo el día 1. Estos envoltorios reemplazan esos casos por
# `core.ui.estado_vacio()`, sin tocar `core.analytics` (los datos siguen
# siendo los mismos; solo cambia qué se pinta cuando están vacíos).
_METODOS = {"efectivo": "Efectivo", "datafono": "Datáfono", "transferencia": "Transferencia",
            "sistecredito": "Sistecrédito", "cambio": "Cambio (saldo a favor)"}
_CANALES = {"tienda": "Tienda", "instagram": "Instagram", "whatsapp": "WhatsApp"}


def _barras_metodo_pago(registros: list[dict], mensaje: str) -> None:
    barras_ranking(
        [(_METODOS.get(str(r["metodo"]), str(r["metodo"])), int(r["total"])) for r in registros],
        detalle=[f"{int(r.get('nro_pagos', 0))} pago(s)" for r in registros],
        vacio=mensaje,
    )


def _barras_campo(registros: list[dict], campo: str, mensaje: str, nombres: dict | None = None) -> None:
    barras_ranking(
        [((nombres or {}).get(str(r[campo]), str(r[campo]) or "Sin categoría"), int(r["ventas_netas"])) for r in registros],
        vacio=mensaje,
    )


def _tabla_ventas_del_dia(registros: list[dict], tiene_completo: bool) -> None:
    columnas = [
        {"clave": "fecha_hora_utc", "titulo": "Hora", "tipo": "hora_utc"},
        {"clave": "numero", "titulo": "Venta"},
        {"clave": "cliente_nombre", "titulo": "Cliente"},
        {"clave": "canal", "titulo": "Canal"},
    ]
    if tiene_completo:
        columnas.append({"clave": "vendedor_nombre", "titulo": "Vendedor"})
    columnas.append({"clave": "total", "titulo": "Total", "tipo": "dinero", "destacar": True})
    filas = [dict(r, canal=_CANALES.get(str(r.get("canal")), r.get("canal"))) for r in reversed(registros)]
    tabla_html(filas, columnas, vacio="Todavía no se ha registrado ninguna venta hoy.", icono_vacio="receipt_long")


def _grafica_top_o_vacio(registros: list[dict], campo_y: str, etiqueta: str, titulo: str, key: str, mensaje: str) -> None:
    if not registros:
        estado_vacio(mensaje, icono="bar_chart")
        return
    st.plotly_chart(_grafica_top(registros, campo_y, etiqueta, titulo), use_container_width=True, key=key)


def _hay_movimiento(barras: list[dict], campo: str = "ventas_netas") -> bool:
    return any(int(b.get(campo, 0) or 0) != 0 for b in barras)


def _grafica_barras_o_vacio(barras: list[dict], titulo: str, key: str, mensaje: str) -> None:
    if not _hay_movimiento(barras):
        estado_vacio(mensaje, icono="bar_chart")
        return
    st.plotly_chart(_grafica_barras(barras, titulo), use_container_width=True, key=key)


def _boton_excel(ctx: ViewContext, tipo: str, fecha_local: date, rol: str, usuario_id: str | None) -> None:
    if st.button("Exportar a Excel", key=f"exportar_{tipo}", icon=":material/download:"):
        contenido = exportar_periodo_excel(ctx.storage, tipo, fecha_local, rol, usuario_id=usuario_id)
        st.download_button(
            "Descargar .xlsx",
            data=contenido,
            on_click="ignore",
            file_name=f"olatata_analisis_{tipo}_{fecha_local.isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"descargar_{tipo}",
            icon=":material/task:",
        )


def _render_hoy(ctx: ViewContext, hoy_local: date, rol: str, usuario_id: str | None, tiene_completo: bool) -> None:
    kpis = kpis_hoy(ctx.storage, hoy_local, rol, usuario_id=usuario_id)
    _kpi_row(kpis, tiene_completo)

    c1, c2 = st.columns(2)
    with c1:
        kpi_card(
            "vs. ayer", format_cop(kpis["comparativo_ayer"]["actual"]),
            delta=kpis["comparativo_ayer"]["variacion_pct"], icono="calendar_today",
        )
    with c2:
        kpi_card(
            "vs. mismo día semana pasada", format_cop(kpis["comparativo_semana_pasada"]["actual"]),
            delta=kpis["comparativo_semana_pasada"]["variacion_pct"], icono="date_range",
        )

    with card(acento="superior"):
        titulo_seccion("Ventas por hora")
        ventas_por_hora = kpis["ventas_por_hora"]
        if not _hay_movimiento(ventas_por_hora, campo="total"):
            estado_vacio("Todavía no hay ventas hoy.", "Las ventas que registres van a aparecer aquí, hora por hora.", icono="bar_chart")
        else:
            df_horas = pd.DataFrame(ventas_por_hora)
            fig = go.Figure(go.Bar(x=df_horas["hora"], y=df_horas["total"], marker_color=_COLOR_PRIMARIO, text=[format_cop(v) for v in df_horas["total"]]))
            fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f", showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="hoy_ventas_por_hora")

    with card(acento="superior"):
        titulo_seccion("Por método de pago")
        _barras_metodo_pago(kpis["por_metodo_pago"], "Todavía no hay pagos registrados hoy.")
        st.metric("Flujo de caja (sin 'Cambio')", format_cop(kpis["flujo_caja"]))

    colc, cold = st.columns(2)
    with colc:
        with card(acento="superior"):
            titulo_seccion("Por canal")
            _barras_campo(kpis["por_canal"], "canal", "Todavía no hay ventas por canal hoy.", _CANALES)
    with cold:
        with card(acento="superior"):
            titulo_seccion("Por categoría")
            _barras_campo(kpis["por_categoria"], "categoria", "Todavía no hay ventas por categoría hoy.")

    with card(acento="superior"):
        titulo_seccion("Top 10 por unidades")
        _grafica_top_o_vacio(
            kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades",
            "hoy_top_unidades", "Todavía no hay productos vendidos hoy.",
        )
    if tiene_completo and kpis.get("por_ganancia"):
        with card(acento="superior"):
            titulo_seccion("Top 10 por ganancia")
            _grafica_top_o_vacio(
                kpis["por_ganancia"], "ganancia", "dinero", "Top 10 por ganancia",
                "hoy_top_ganancia", "Todavía no hay ganancia registrada hoy.",
            )

    with card(acento="superior"):
        titulo_seccion("Ventas del día")
        _tabla_ventas_del_dia(kpis["ventas_del_dia"], tiene_completo)

    if tiene_capacidad(rol, "cuadre_caja"):
        with card(acento="izquierdo"):
            titulo_seccion("Cuadre de caja")
            with st.form("form_cuadre_caja"):
                base_inicial = st.number_input("Base inicial", min_value=0, step=1000, value=0)
                efectivo_contado = st.number_input("Efectivo contado", min_value=0, step=1000, value=0)
                nota = st.text_area("Nota", value="")
                enviado = st.form_submit_button("Registrar cuadre", type="primary", icon=":material/point_of_sale:")
            if enviado:
                try:
                    resultado = registrar_cuadre_caja(
                        ctx.storage,
                        rol,
                        hoy_local,
                        "principal",
                        int(base_inicial),
                        int(efectivo_contado),
                        nota,
                        usuario_id=getattr(ctx.usuario, "id", None),
                    )
                    # Dos montos "$ ..." (R1) en el mismo texto markdown
                    # pueden leerse como un bloque de LaTeX ("$...$") y
                    # mostrar "**"/texto crudo en vez del número (capa
                    # visual) — se escapa el signo antes de mostrarlo.
                    esperado_md = format_cop(resultado["efectivo_esperado"]).replace("$", r"\$")
                    diferencia_md = format_cop(resultado["diferencia"]).replace("$", r"\$")
                    st.success(f"Cuadre registrado. Esperado: {esperado_md} · Diferencia: {diferencia_md}")
                    ctx.rerun()
                except PermisoDenegadoError as exc:
                    st.error(str(exc))

    _boton_excel(ctx, "dia", hoy_local, rol, usuario_id)


def _render_semana(ctx: ViewContext, hoy_local: date, rol: str, usuario_id: str | None, tiene_completo: bool) -> None:
    kpis = kpis_semana(ctx.storage, hoy_local, rol, usuario_id=usuario_id)
    _kpi_row(kpis, tiene_completo)

    with card(acento="superior"):
        titulo_seccion("Ventas netas por día (lunes → hoy)")
        _grafica_barras_o_vacio(
            kpis["barras_por_dia"], "Ventas netas por día (lunes → hoy)",
            "semana_barras_por_dia", "Todavía no hay ventas esta semana.",
        )

    kpi_card(
        "vs. semana anterior (mismos días transcurridos)", format_cop(kpis["comparativo_semana_anterior"]["actual"]),
        delta=kpis["comparativo_semana_anterior"]["variacion_pct"], icono="calendar_view_week",
    )

    with card(acento="superior"):
        titulo_seccion("Top productos de la semana")
        _grafica_top_o_vacio(
            kpis["por_unidades"], "cantidad", "unidades", "Top por unidades",
            "semana_top_unidades", "Todavía no hay productos vendidos esta semana.",
        )

    _boton_excel(ctx, "semana", hoy_local, rol, usuario_id)


def _render_mes(ctx: ViewContext, hoy_local: date, rol: str, usuario_id: str | None, tiene_completo: bool) -> None:
    kpis = kpis_mes(ctx.storage, hoy_local, rol, usuario_id=usuario_id)
    _kpi_row(kpis, tiene_completo)

    with card(acento="superior"):
        titulo_seccion("Ventas netas por día (día 1 → hoy)")
        _grafica_barras_o_vacio(
            kpis["barras_por_dia"], "Ventas netas por día (día 1 → hoy)",
            "mes_barras_por_dia", "Todavía no hay ventas este mes.",
        )

    colc, cold = st.columns(2)
    with colc:
        with card(acento="superior"):
            titulo_seccion("Por categoría")
            _barras_campo(kpis["por_categoria"], "categoria", "Todavía no hay ventas por categoría este mes.")
    with cold:
        with card(acento="superior"):
            titulo_seccion("Por canal")
            _barras_campo(kpis["por_canal"], "canal", "Todavía no hay ventas por canal este mes.", _CANALES)

    with card(acento="superior"):
        titulo_seccion("Top 10 por unidades")
        _grafica_top_o_vacio(
            kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades",
            "mes_top_unidades", "Todavía no hay productos vendidos este mes.",
        )
    if tiene_completo and kpis.get("por_ganancia"):
        with card(acento="superior"):
            titulo_seccion("Top 10 por ganancia")
            _grafica_top_o_vacio(
                kpis["por_ganancia"], "ganancia", "dinero", "Top 10 por ganancia",
                "mes_top_ganancia", "Todavía no hay ganancia registrada este mes.",
            )

    kpi_card(
        "vs. mes anterior (mismo día transcurrido)", format_cop(kpis["comparativo_mes_anterior"]["actual"]),
        delta=kpis["comparativo_mes_anterior"]["variacion_pct"], icono="calendar_month",
    )
    st.caption(f"Proyección de cierre (estimado): {format_cop(kpis['proyeccion_cierre']['valor'])}")

    if tiene_completo:
        with card(acento="superior"):
            titulo_seccion("Inventario")
            inv = kpis["valor_inventario"]
            colx, coly, colz, colw = st.columns(4)
            colx.metric("Valor al costo", format_cop(inv["al_costo"]))
            coly.metric("Valor al precio", format_cop(inv["al_precio"]))
            bajo = kpis["productos_bajo_minimo_y_agotados"]
            colz.metric("Bajo mínimo", bajo["bajo_minimo"])
            colw.metric("Agotados", bajo["agotados"])

    with card(acento="superior"):
        titulo_seccion("Stock sin ventas en 30 días")
        st.caption("Productos con existencias que no se vendieron en el último mes: candidatos a promoción.")
        tabla_html(
            sorted(kpis["stock_sin_ventas_30_dias"], key=lambda r: -int(r["stock"])),
            [{"clave": "nombre", "titulo": "Producto", "destacar": True},
             {"clave": "stock", "titulo": "Unidades", "tipo": "numero"}],
            vacio="Todo el stock tuvo ventas en los últimos 30 días.",
            icono_vacio="verified",
        )

    _boton_excel(ctx, "mes", hoy_local, rol, usuario_id)


def _render_meses_anteriores(ctx: ViewContext, hoy_local: date, rol: str) -> None:
    opciones = []
    cursor = date(hoy_local.year, hoy_local.month, 1)
    for _ in range(12):
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)
        opciones.append(cursor)

    etiquetas = [d.strftime("%Y-%m") for d in opciones]
    seleccion = st.selectbox("Mes", etiquetas) if etiquetas else None
    if not seleccion:
        estado_vacio("No hay meses anteriores para mostrar.", icono="calendar_month")
        return

    year, month = (int(x) for x in seleccion.split("-"))
    try:
        kpis = kpis_mes_cerrado(ctx.storage, year, month, rol)
    except Exception as exc:
        st.warning(f"No se encontró un cierre archivado para {seleccion}: {exc}")
        return

    if kpis["tickets"] == 0:
        estado_vacio(f"No hay datos archivados para {seleccion}.", icono="calendar_month")
        return

    tiene_completo = tiene_capacidad(rol, "ver_analisis_completo")
    _kpi_row(kpis, tiene_completo)
    with card(acento="superior"):
        titulo_seccion("Top 10 por unidades")
        _grafica_top_o_vacio(
            kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades",
            "anteriores_top_unidades", f"No hay productos vendidos archivados para {seleccion}.",
        )
