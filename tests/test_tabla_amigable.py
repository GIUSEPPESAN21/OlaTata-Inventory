"""`core.ui.tabla_amigable`: tablas legibles (dinero COP, hora Bogotá,
valores y encabezados en español). Solo presentación."""
from __future__ import annotations

import pandas as pd

from core.ui import tabla_amigable


def test_encabezados_tecnicos_pasan_a_espanol():
    df = pd.DataFrame([{"stock_actual": 3, "codigo_barras": "770", "columna_rara_x": 1}])
    assert list(tabla_amigable(df).columns) == ["Stock actual", "Código de barras", "Columna rara x"]


def test_dinero_entero_se_formatea_en_cop_y_texto_se_respeta():
    df = pd.DataFrame([{"total": 65000, "precio": "$ 89.000", "costo": None}])
    fila = tabla_amigable(df).iloc[0]
    assert fila["Total"] == "$ 65.000"
    assert fila["Precio"] == "$ 89.000"  # ya venía formateado
    assert fila["Costo"] == "—"


def test_fecha_utc_se_muestra_en_hora_de_bogota():
    df = pd.DataFrame([{"fecha_hora_utc": "2026-11-13T04:30:00+00:00"}])
    assert tabla_amigable(df).iloc[0]["Fecha y hora"] == "12/11/2026 11:30 p.m."


def test_metodos_y_canales_legibles():
    df = pd.DataFrame([{"metodo": "sistecredito", "canal": "whatsapp"}, {"metodo": "otro", "canal": "tienda"}])
    t = tabla_amigable(df)
    assert list(t["Método de pago"]) == ["Sistecrédito", "otro"]
    assert list(t["Canal"]) == ["WhatsApp", "Tienda"]


def test_no_modifica_el_dataframe_original():
    df = pd.DataFrame([{"total": 1000}])
    tabla_amigable(df)
    assert list(df.columns) == ["total"] and df.iloc[0]["total"] == 1000
