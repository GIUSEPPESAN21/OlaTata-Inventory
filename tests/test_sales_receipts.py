"""Pruebas de `core.receipts` (texto del recibo + enlace wa.me)."""
from __future__ import annotations

import uuid

import pandas as pd

from core import schema
from core.permissions import VENDEDOR
from core.receipts import TELEFONO_PLACEHOLDER, generar_texto_recibo, generar_url_whatsapp
from core.sales import confirmar_venta


def _seed_producto(storage, producto_id="P-1", precio=90_000, costo=50_000, stock=10):
    with storage.transaction() as tx:
        productos_df = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": producto_id,
                    "nombre": "Bolso Negro",
                    "categoria": "Bolsos",
                    "color": "Negro",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": costo,
                    "precio": precio,
                    "stock_minimo": 1,
                    "codigo_barras": producto_id,
                    "activo": True,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([productos_df, nueva], ignore_index=True))
        stock_df = tx.read_sheet(schema.STOCK)
        nueva_stock = pd.DataFrame(
            [
                {
                    "producto_id": producto_id,
                    "sede_id": schema.SEDE_PRINCIPAL,
                    "cantidad": stock,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
        tx.write_sheet(schema.STOCK, pd.concat([stock_df, nueva_stock], ignore_index=True))


def _vender(storage, cantidad=1, cliente_nombre=""):
    return confirmar_venta(
        storage,
        VENDEDOR,
        str(uuid.uuid4()),
        [{"producto_id": "P-1", "cantidad": cantidad}],
        [{"metodo": "efectivo", "monto": 90_000 * cantidad}],
        None,
        None,
        "tienda",
        {"nombre": cliente_nombre} if cliente_nombre else None,
        "U-1",
        "Ana",
    )


def test_texto_recibo_contiene_numero_total_y_productos(storage):
    _seed_producto(storage)
    venta = _vender(storage, cantidad=2, cliente_nombre="Clienta X")
    texto = generar_texto_recibo(venta)
    assert venta.numero in texto
    assert "$ 180.000" in texto  # total formateado (R1)
    assert "Bolso Negro" in texto
    assert "Clienta X" in texto


def test_texto_recibo_sin_cliente_no_falla(storage):
    _seed_producto(storage)
    venta = _vender(storage, cantidad=1)
    texto = generar_texto_recibo(venta)
    assert "Cliente:" not in texto


def test_url_whatsapp_usa_placeholder_si_no_hay_config(storage):
    _seed_producto(storage)
    venta = _vender(storage, cantidad=1)
    url = generar_url_whatsapp(venta)
    assert url.startswith(f"https://wa.me/{TELEFONO_PLACEHOLDER}?text=")


def test_url_whatsapp_usa_telefono_de_config_y_codifica_el_texto(storage):
    _seed_producto(storage)
    venta = _vender(storage, cantidad=1)
    url = generar_url_whatsapp(venta, telefono_whatsapp="+57 300 111 2222")
    assert url.startswith("https://wa.me/573001112222?text=")
    assert " " not in url  # el espacio se codifica (quote)
