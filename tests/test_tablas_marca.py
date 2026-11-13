"""Tablas, filas y barras de marca (core/ui.py): reemplazan la cuadrícula
de st.dataframe. Se prueba el HTML generado (sin navegador) y, sobre todo,
que el texto libre siempre se escape."""
from __future__ import annotations

from unittest.mock import patch

from core import ui


def _capturar(funcion, *args, **kwargs) -> str:
    salida: list[str] = []
    with patch("streamlit.markdown", side_effect=lambda html, **k: salida.append(html)), \
         patch("core.ui.inyectar_identidad_visual"), patch("core.ui.estado_vacio") as vacio:
        funcion(*args, **kwargs)
    return "".join(salida) if salida else f"VACIO:{vacio.call_args}"


def test_tabla_html_formatea_y_escapa():
    html = _capturar(
        ui.tabla_html,
        [{"producto": "<script>alert(1)</script>", "total": 98000, "fecha": "2026-11-13T20:45:00+00:00", "x": None}],
        [{"clave": "producto", "titulo": "Producto", "destacar": True},
         {"clave": "total", "titulo": "Total", "tipo": "dinero"},
         {"clave": "fecha", "titulo": "Hora", "tipo": "hora_utc"},
         {"clave": "x", "titulo": "Vacío"}],
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "$ 98.000" in html
    assert "3:45 p.m." in html or "03:45 p.m." in html  # hora de Bogotá
    assert 'data-etiqueta="Total"' in html  # etiqueta para la vista de celular
    assert "ot-tabla__destacar" in html and "—" in html


def test_tabla_html_vacia_muestra_estado_vacio():
    assert _capturar(ui.tabla_html, [], [{"clave": "a", "titulo": "A"}], vacio="Nada").startswith("VACIO")


def test_barras_ranking_ordena_proporciona_y_marca_negativos():
    html = _capturar(
        ui.barras_ranking, [("Efectivo", 50000), ("Datáfono", 100000), ("Ajuste <b>", -20000)],
        detalle=["1 pago(s)", "2 pago(s)", "x"],
    )
    assert html.index("Datáfono") < html.index("Efectivo") < html.index("Ajuste")
    assert "width:100%" in html and "width:50%" in html
    assert "ot-barra--negativa" in html and "&lt;b&gt;" in html and "2 pago(s)" in html
    assert _capturar(ui.barras_ranking, [], vacio="x").startswith("VACIO")


def test_fila_html_escapa_y_muestra_lo_esencial():
    html = ui.fila_html("Bolso <i>", sub="Cliente & Co", meta="N.º 1", valor="$ 1.000",
                        chips_html=ui.chip_estado("Anulada", "error"))
    assert "Bolso &lt;i&gt;" in html and "Cliente &amp; Co" in html
    assert "ot-fila__valor" in html and "ot-chip--error" in html
    assert "ot-fila__derecha" not in ui.fila_html("Solo título")


def test_chip_stock_por_estado():
    assert "Agotado" in ui.chip_stock(0)
    assert "stock bajo" in ui.chip_stock(2, minimo=3)
    assert "5 en stock" in ui.chip_stock(5, minimo=3)
    assert "Inactivo" in ui.chip_stock(5, activo=False)


def test_paginado_se_reinicia_al_cambiar_filtros():
    import streamlit as st

    st.session_state.clear()
    assert ui.limite_paginado("lista", "a", paso=10) == 10
    st.session_state["lista__limite"] = 30
    assert ui.limite_paginado("lista", "a", paso=10) == 30
    assert ui.limite_paginado("lista", "b", paso=10) == 10
