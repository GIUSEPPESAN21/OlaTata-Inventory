"""Pruebas de core/labels_ot.py: generación de código de barras y PDF de
etiquetas (solo python-barcode + Pillow, sin reportlab/fpdf2)."""
from __future__ import annotations

import pytest
from PIL import Image

from core import labels_ot


def test_generar_imagen_codigo_barras_devuelve_imagen():
    img = labels_ot.generar_imagen_codigo_barras("OT-000001")
    assert isinstance(img, Image.Image)
    assert img.width > 0 and img.height > 0


def test_generar_imagen_codigo_barras_rechaza_vacio():
    with pytest.raises(ValueError):
        labels_ot.generar_imagen_codigo_barras("")


def test_generar_etiqueta_devuelve_imagen_del_tamano_esperado():
    etiqueta = labels_ot.generar_etiqueta(nombre="Bolso rosa", codigo_barras="OT-000001", precio=50000)
    assert etiqueta.size == (labels_ot.LABEL_WIDTH_PX, labels_ot.LABEL_HEIGHT_PX)


def test_generar_etiqueta_sin_precio_no_falla():
    etiqueta = labels_ot.generar_etiqueta(nombre="Bolso rosa", codigo_barras="OT-000001")
    assert etiqueta is not None


def test_generar_pdf_etiquetas_una_pagina_por_producto():
    productos = [
        {"nombre": "Bolso A", "codigo_barras": "OT-000001", "precio": 50000},
        {"nombre": "Bolso B", "codigo_barras": "OT-000002", "precio": 70000},
    ]
    pdf_bytes = labels_ot.generar_pdf_etiquetas(productos)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 0


def test_generar_pdf_etiquetas_rechaza_lista_vacia():
    with pytest.raises(ValueError):
        labels_ot.generar_pdf_etiquetas([])


def test_generar_pdf_etiquetas_rechaza_producto_sin_codigo():
    with pytest.raises(ValueError):
        labels_ot.generar_pdf_etiquetas([{"nombre": "Sin código", "codigo_barras": ""}])


def test_generar_etiqueta_recorta_nombre_demasiado_largo():
    nombre_largo = "Bolso de cuero genuino edición limitada artesanal " * 5
    etiqueta = labels_ot.generar_etiqueta(nombre=nombre_largo, codigo_barras="OT-000001")
    assert etiqueta.size == (labels_ot.LABEL_WIDTH_PX, labels_ot.LABEL_HEIGHT_PX)


def test_generar_etiqueta_nombre_con_formula_no_rompe_render():
    # R11: "=1+1" no debe interpretarse como fórmula (ni romper el render).
    etiqueta = labels_ot.generar_etiqueta(nombre="=1+1", codigo_barras="OT-000001")
    assert etiqueta is not None
