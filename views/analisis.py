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
from core.ui import card, encabezado_pagina, estado_vacio, kpi_card, titulo_seccion
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

    encabezado_pagina("Análisis", icono="bar_chart")
    if not tiene_completo:
        st.caption("Vista de vendedor: ventas, unidades y tickets de tu turno. Sin costos ni ganancia.")

    tab_hoy, tab_semana, tab_mes, tab_anteriores = st.tabs(["Hoy", "Semana", "Mes", "Meses anteriores"])

    with tab_hoy:
        _render_hoy(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_semana:
        _render_semana(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_mes:
        _render_mes(ctx, hoy_local, rol, usuario_id, tiene_completo)
    with tab_anteriores:
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
    fig.update_layout(title=titulo, yaxis_tickprefix="$", yaxis_tickformat=",.0f", showlegend=False)
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
    fig.update_layout(title=titulo, showlegend=False)
    if etiqueta == "dinero":
        fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f")
    return fig


def _boton_excel(ctx: ViewContext, tipo: str, fecha_local: date, rol: str, usuario_id: str | None) -> None:
    if st.button("Exportar a Excel", key=f"exportar_{tipo}", icon=":material/download:"):
        contenido = exportar_periodo_excel(ctx.storage, tipo, fecha_local, rol, usuario_id=usuario_id)
        st.download_button(
            "Descargar .xlsx",
            data=contenido,
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
        titulo_seccion("Ventas por hora", centrado=False)
        df_horas = pd.DataFrame(kpis["ventas_por_hora"])
        fig = go.Figure(go.Bar(x=df_horas["hora"], y=df_horas["total"], marker_color=_COLOR_PRIMARIO, text=[format_cop(v) for v in df_horas["total"]]))
        fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f", showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="hoy_ventas_por_hora")

    with card(acento="superior"):
        titulo_seccion("Por método de pago", centrado=False)
        st.dataframe(pd.DataFrame(kpis["por_metodo_pago"]), use_container_width=True, hide_index=True, key="hoy_por_metodo_pago")
        st.metric("Flujo de caja (sin 'Cambio')", format_cop(kpis["flujo_caja"]))

    colc, cold = st.columns(2)
    with colc:
        with card(acento="superior"):
            titulo_seccion("Por canal", centrado=False)
            st.dataframe(pd.DataFrame(kpis["por_canal"]), use_container_width=True, hide_index=True, key="hoy_por_canal")
    with cold:
        with card(acento="superior"):
            titulo_seccion("Por categoría", centrado=False)
            st.dataframe(pd.DataFrame(kpis["por_categoria"]), use_container_width=True, hide_index=True, key="hoy_por_categoria")

    with card(acento="superior"):
        titulo_seccion("Top 10 por unidades", centrado=False)
        st.plotly_chart(_grafica_top(kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades"), use_container_width=True, key="hoy_top_unidades")
    if tiene_completo and kpis.get("por_ganancia"):
        with card(acento="superior"):
            titulo_seccion("Top 10 por ganancia", centrado=False)
            st.plotly_chart(_grafica_top(kpis["por_ganancia"], "ganancia", "dinero", "Top 10 por ganancia"), use_container_width=True, key="hoy_top_ganancia")

    with card(acento="superior"):
        titulo_seccion("Ventas del día", centrado=False)
        st.dataframe(pd.DataFrame(kpis["ventas_del_dia"]), use_container_width=True, hide_index=True, key="hoy_ventas_del_dia")

    if tiene_capacidad(rol, "cuadre_caja"):
        with card(acento="izquierdo"):
            titulo_seccion("Cuadre de caja", centrado=False)
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
                    st.success(
                        f"Cuadre registrado. Esperado: {format_cop(resultado['efectivo_esperado'])} · "
                        f"Diferencia: {format_cop(resultado['diferencia'])}"
                    )
                    ctx.rerun()
                except PermisoDenegadoError as exc:
                    st.error(str(exc))

    _boton_excel(ctx, "dia", hoy_local, rol, usuario_id)


def _render_semana(ctx: ViewContext, hoy_local: date, rol: str, usuario_id: str | None, tiene_completo: bool) -> None:
    kpis = kpis_semana(ctx.storage, hoy_local, rol, usuario_id=usuario_id)
    _kpi_row(kpis, tiene_completo)

    with card(acento="superior"):
        titulo_seccion("Ventas netas por día (lunes → hoy)", centrado=False)
        st.plotly_chart(_grafica_barras(kpis["barras_por_dia"], "Ventas netas por día (lunes → hoy)"), use_container_width=True, key="semana_barras_por_dia")

    kpi_card(
        "vs. semana anterior (mismos días transcurridos)", format_cop(kpis["comparativo_semana_anterior"]["actual"]),
        delta=kpis["comparativo_semana_anterior"]["variacion_pct"], icono="calendar_view_week",
    )

    with card(acento="superior"):
        titulo_seccion("Top productos de la semana", centrado=False)
        st.plotly_chart(_grafica_top(kpis["por_unidades"], "cantidad", "unidades", "Top por unidades"), use_container_width=True, key="semana_top_unidades")

    _boton_excel(ctx, "semana", hoy_local, rol, usuario_id)


def _render_mes(ctx: ViewContext, hoy_local: date, rol: str, usuario_id: str | None, tiene_completo: bool) -> None:
    kpis = kpis_mes(ctx.storage, hoy_local, rol, usuario_id=usuario_id)
    _kpi_row(kpis, tiene_completo)

    with card(acento="superior"):
        titulo_seccion("Ventas netas por día (día 1 → hoy)", centrado=False)
        st.plotly_chart(_grafica_barras(kpis["barras_por_dia"], "Ventas netas por día (día 1 → hoy)"), use_container_width=True, key="mes_barras_por_dia")

    colc, cold = st.columns(2)
    with colc:
        with card(acento="superior"):
            titulo_seccion("Por categoría", centrado=False)
            st.dataframe(pd.DataFrame(kpis["por_categoria"]), use_container_width=True, hide_index=True, key="mes_por_categoria")
    with cold:
        with card(acento="superior"):
            titulo_seccion("Por canal", centrado=False)
            st.dataframe(pd.DataFrame(kpis["por_canal"]), use_container_width=True, hide_index=True, key="mes_por_canal")

    with card(acento="superior"):
        titulo_seccion("Top 10 por unidades", centrado=False)
        st.plotly_chart(_grafica_top(kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades"), use_container_width=True, key="mes_top_unidades")
    if tiene_completo and kpis.get("por_ganancia"):
        with card(acento="superior"):
            titulo_seccion("Top 10 por ganancia", centrado=False)
            st.plotly_chart(_grafica_top(kpis["por_ganancia"], "ganancia", "dinero", "Top 10 por ganancia"), use_container_width=True, key="mes_top_ganancia")

    kpi_card(
        "vs. mes anterior (mismo día transcurrido)", format_cop(kpis["comparativo_mes_anterior"]["actual"]),
        delta=kpis["comparativo_mes_anterior"]["variacion_pct"], icono="calendar_month",
    )
    st.caption(f"Proyección de cierre (estimado): {format_cop(kpis['proyeccion_cierre']['valor'])}")

    if tiene_completo:
        with card(acento="superior"):
            titulo_seccion("Inventario", centrado=False)
            inv = kpis["valor_inventario"]
            colx, coly, colz, colw = st.columns(4)
            colx.metric("Valor al costo", format_cop(inv["al_costo"]))
            coly.metric("Valor al precio", format_cop(inv["al_precio"]))
            bajo = kpis["productos_bajo_minimo_y_agotados"]
            colz.metric("Bajo mínimo", bajo["bajo_minimo"])
            colw.metric("Agotados", bajo["agotados"])

    with card(acento="superior"):
        titulo_seccion("Stock sin ventas en 30 días", centrado=False)
        st.dataframe(pd.DataFrame(kpis["stock_sin_ventas_30_dias"]), use_container_width=True, hide_index=True, key="mes_stock_sin_ventas")

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
        titulo_seccion("Top 10 por unidades", centrado=False)
        st.plotly_chart(_grafica_top(kpis["por_unidades"], "cantidad", "unidades", "Top 10 por unidades"), use_container_width=True, key="anteriores_top_unidades")
