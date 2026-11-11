"""R3/R6: 20 hilos vendiendo la última unidad -> exactamente 1 éxito,
19 rechazos limpios (ninguna excepción inesperada, ninguna sobreventa).
Mismo patrón de `threading.Thread` que `tests/test_storage.py`."""
from __future__ import annotations

import threading
import uuid

import pandas as pd

from core import schema
from core.permissions import VENDEDOR
from core.sales import StockInsuficienteError, confirmar_venta
from core.storage import Storage


def _seed_producto_storage(storage, producto_id="P-1", precio=90_000, costo=50_000, stock=1):
    with storage.transaction() as tx:
        productos_df = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": producto_id,
                    "nombre": "Bolso Único",
                    "categoria": "Bolsos",
                    "color": "Rojo",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": costo,
                    "precio": precio,
                    "stock_minimo": 0,
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


def test_20_hilos_vendiendo_la_ultima_unidad_exactamente_uno_exitoso(tmp_path):
    storage = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False)
    _seed_producto_storage(storage, stock=1)

    exitos = []
    rechazos = []
    errores_inesperados = []

    def intentar_vender():
        try:
            venta = confirmar_venta(
                storage,
                VENDEDOR,
                str(uuid.uuid4()),
                [{"producto_id": "P-1", "cantidad": 1}],
                [{"metodo": "efectivo", "monto": 90_000}],
                None,
                None,
                "tienda",
                None,
                "U-1",
                "Ana",
            )
            exitos.append(venta)
        except StockInsuficienteError as exc:
            rechazos.append(exc)
        except Exception as exc:  # pragma: no cover - solo si algo va mal
            errores_inesperados.append(exc)

    hilos = [threading.Thread(target=intentar_vender) for _ in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)

    assert not any(h.is_alive() for h in hilos)
    assert not errores_inesperados
    assert len(exitos) == 1
    assert len(rechazos) == 19

    ventas_df = storage.read_sheet(schema.VENTAS)
    assert len(ventas_df) == 1
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df.iloc[0]["cantidad"]) == 0  # nunca queda negativo (R3), sin sobreventa
