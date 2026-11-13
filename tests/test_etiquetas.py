"""Etiquetas físicas para la impresora DigitalPOS (core/etiquetas.py).

La prueba clave decodifica las barras generadas con un lector real por
software (zxing-cpp), con desenfoque simulado de impresión térmica: así
se comprueba que el lector USB del local las va a poder leer.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageFilter

from core import etiquetas as et
from core.permissions import PermisoDenegadoError

zxingcpp = pytest.importorskip("zxingcpp")

CASOS = [
    ("Bolso 98", et.codigo_interno("OT-001367"), 98000),
    ("Cartera de cuero sintético rosa con cadena dorada grande", et.codigo_interno("OT-000002"), 1_250_000),
    ("Gafas", "7701234567890", 35000),
    ("Ñandú", et.codigo_interno("OT-999999"), None),
]


@pytest.mark.parametrize("perfil", list(et.PERFILES_PREDEFINIDOS.values()), ids=lambda p: p.nombre)
@pytest.mark.parametrize("nombre,codigo,precio", CASOS)
def test_el_lector_puede_leer_cada_etiqueta(perfil, nombre, codigo, precio):
    img = et.componer_etiqueta(et.ItemEtiqueta(nombre, codigo, precio), perfil)
    assert img.mode == "1"  # blanco y negro puro para la térmica
    assert img.size == (perfil.mm_a_px(perfil.ancho_mm), perfil.mm_a_px(perfil.alto_mm))
    impresa = img.convert("L").filter(ImageFilter.GaussianBlur(0.8))
    assert [r.text for r in zxingcpp.read_barcodes(impresa)] == [codigo]


def test_codigo_interno_ida_y_vuelta():
    assert et.codigo_interno("OT-000123") == "20000123"
    assert et.id_desde_codigo_interno("20000123") == "OT-000123"
    assert et.id_desde_codigo_interno("7701234567890") is None
    with pytest.raises(ValueError):
        et.codigo_interno("sin-numero")
    with pytest.raises(ValueError):
        et.codigo_interno("OT-1000000")


def test_codigo_para_producto_prefiere_el_propio():
    assert et.codigo_para_producto("OT-000005", "7701234567890") == "7701234567890"
    for vacio in ("", None, "nan", "  "):
        assert et.codigo_para_producto("OT-000005", vacio) == "20000005"


def test_normalizar_lectura_escaner_teclado_latino():
    assert et.normalizar_lectura_escaner(" OT'000001\r") == "OT-000001"
    assert et.normalizar_lectura_escaner("20000001\t") == "20000001"


def test_filas_agrupan_por_columnas_y_pdf_tiene_tamano_fisico():
    perfil = et.PERFIL_POR_DEFECTO
    items = [et.ItemEtiqueta("Bolso", et.codigo_interno(f"OT-{i:06d}"), 1000) for i in range(1, 8)]
    filas = et.componer_filas(items, perfil)
    assert len(filas) == 3  # 7 etiquetas / 3 por fila
    pdf = et.generar_pdf(items, perfil)
    assert pdf[:4] == b"%PDF" and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1
    # MediaBox en puntos = mm * 72 / 25.4 (103 mm x 25 mm)
    ancho_pt = filas[0].width / perfil.dpi * 72
    assert abs(ancho_pt - perfil.ancho_fila_mm * 72 / 25.4) < 1.5
    with pytest.raises(ValueError):
        et.componer_filas([], perfil)


def test_calibracion_y_tspl():
    perfil = et.PERFIL_POR_DEFECTO
    assert et.generar_pdf_calibracion(perfil)[:4] == b"%PDF"
    items = [et.ItemEtiqueta("Bolso", "20000001", 98000)] * 4
    tspl = et.generar_tspl(items, perfil)
    assert tspl.count(b"PRINT 1,1") == 2
    assert tspl.startswith(b"SIZE 103 mm,25 mm\r\nGAP 2 mm,0 mm")
    assert et.generar_tspl(items, perfil, invertir=True) != tspl


def test_perfil_valida_y_se_guarda_en_config(storage):
    with pytest.raises(ValueError):
        et.PerfilEtiqueta(columnas=6)
    with pytest.raises(ValueError):
        et.PerfilEtiqueta(dpi=150)
    assert et.cargar_perfil(storage) == et.PERFIL_POR_DEFECTO
    nuevo = et.con_perfil(et.PERFIL_POR_DEFECTO, nombre="Personalizado…", ancho_mm=30.5)
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            et.guardar_perfil(tx, "vendedor", nuevo)
    with storage.transaction() as tx:
        et.guardar_perfil(tx, "admin", nuevo)
    assert et.cargar_perfil(storage) == nuevo
    assert et.perfil_desde_json("{dañado") == et.PERFIL_POR_DEFECTO


def test_codigo_vacio_falla_con_mensaje_claro():
    with pytest.raises(ValueError):
        et.componer_etiqueta(et.ItemEtiqueta("X", "", 1000))


def test_texto_del_recibo_impreso_80mm():
    from core.recibo_impreso import generar_imagen_recibo, generar_pdf_recibo

    venta = {
        "numero": "2026-11-0001", "fecha_hora_utc": "2026-11-13T20:45:00+00:00", "fecha_local": "2026-11-13",
        "canal": "tienda", "subtotal": 98000, "descuento_total": 0, "envio_cobrado": 0, "total": 98000,
        "items": [{"nombre_snapshot": "Bolso 98", "cantidad": 2, "precio_unitario": 49000, "total_linea": 98000}],
        "pagos": [{"metodo": "sistecredito", "monto": 98000}], "cliente_nombre": "",
    }
    img = generar_imagen_recibo(venta, vendedor="Dueña")
    assert img.mode == "1" and img.width == round(80 * 203 / 25.4)
    assert isinstance(img, Image.Image)
    assert generar_pdf_recibo(venta, ancho_papel_mm=58)[:4] == b"%PDF"
    with pytest.raises(ValueError):
        generar_imagen_recibo(venta, ancho_papel_mm=110)
