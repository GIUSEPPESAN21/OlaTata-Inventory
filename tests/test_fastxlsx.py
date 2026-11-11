"""Pruebas de `core.fastxlsx`: el escritor OOXML a mano que reemplaza a
openpyxl en la escritura (hallazgo de rendimiento de A6, §11)."""
from __future__ import annotations

import time

import pandas as pd

from core.fastxlsx import _cell_xml, _col_letter, write_workbook


def test_col_letter_basico():
    assert _col_letter(0) == "A"
    assert _col_letter(25) == "Z"
    assert _col_letter(26) == "AA"
    assert _col_letter(27) == "AB"
    assert _col_letter(51) == "AZ"
    assert _col_letter(52) == "BA"


def test_cell_xml_none_devuelve_vacio():
    assert _cell_xml("A1", None) == ""


def test_cell_xml_bool_true_false():
    assert _cell_xml("A1", True) == '<c r="A1" t="b"><v>1</v></c>'
    assert _cell_xml("A1", False) == '<c r="A1" t="b"><v>0</v></c>'


def test_cell_xml_string_vacia_devuelve_vacio():
    assert _cell_xml("A1", "") == ""


def test_cell_xml_nan_float_devuelve_vacio():
    assert _cell_xml("A1", float("nan")) == ""


def test_cell_xml_numero():
    assert _cell_xml("A1", 1250000) == '<c r="A1"><v>1250000</v></c>'


def test_cell_xml_escapa_caracteres_especiales_xml():
    xml = _cell_xml("A1", "a < b & c > d")
    assert "&lt;" in xml and "&amp;" in xml and "&gt;" in xml


def test_write_workbook_roundtrip_tipos_variados(tmp_path):
    df = pd.DataFrame(
        {
            "id": ["OT-1", "OT-2", "OT-3"],
            "nombre": ["=1+1", "Bolso Ñandú 🎒", ""],
            "cantidad": [1, -5, 1_000_000],
            "activo": [True, False, True],
            "nota": [None, "@SUM(1)", "normal"],
        }
    )
    destino = tmp_path / "out.xlsx"
    write_workbook(destino, {"hoja1": df}, ["hoja1"])

    leido = pd.read_excel(destino, sheet_name="hoja1", engine="openpyxl", dtype=object)
    assert leido.iloc[0]["nombre"] == "=1+1"  # nunca se interpreta como fórmula (R11)
    assert leido.iloc[1]["nombre"] == "Bolso Ñandú 🎒"
    assert int(leido.iloc[1]["cantidad"]) == -5
    assert int(leido.iloc[2]["cantidad"]) == 1_000_000
    assert bool(leido.iloc[0]["activo"]) is True
    assert bool(leido.iloc[1]["activo"]) is False
    assert pd.isna(leido.iloc[0]["nota"])
    assert leido.iloc[1]["nota"] == "@SUM(1)"


def test_write_workbook_respeta_orden_de_hojas(tmp_path):
    destino = tmp_path / "out.xlsx"
    df_vacio = pd.DataFrame(columns=["x"])
    write_workbook(destino, {"b": df_vacio, "a": df_vacio}, ["a", "b"])
    hojas = pd.read_excel(destino, sheet_name=None, engine="openpyxl")
    assert list(hojas.keys()) == ["a", "b"]


def test_escritura_de_un_mes_de_alto_volumen_respeta_presupuesto(tmp_path):
    """Regresión del hallazgo de A6: con openpyxl normal esto tardaba
    2-3.5s; el presupuesto del §11 exige <500ms en local. Umbral aquí:
    2s, generoso para no ser frágil en CI compartido, pero suficiente
    para detectar una regresión grave si alguien vuelve a openpyxl."""
    ventas = pd.DataFrame(
        {
            "id": [f"V-{i}" for i in range(1500)],
            "total": list(range(1500)),
            "nota": ["cliente frecuente" for _ in range(1500)],
        }
    )
    items = pd.DataFrame(
        {
            "id": [f"I-{i}" for i in range(3750)],
            "cantidad": list(range(3750)),
            "nombre_snapshot": ["Bolso de cuero negro" for _ in range(3750)],
        }
    )
    destino = tmp_path / "out.xlsx"
    t0 = time.perf_counter()
    write_workbook(destino, {"ventas": ventas, "venta_items": items}, ["ventas", "venta_items"])
    duracion = time.perf_counter() - t0
    assert duracion < 2.0, f"write_workbook tardó {duracion:.2f}s, se esperaba <2s"
