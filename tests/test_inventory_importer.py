"""Pruebas de core/importer.py: validación previa (sin escribir) y
aplicación de la importación inicial (R3, R4, R11)."""
from __future__ import annotations

import pytest

from core import importer, schema
from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError


def _fila_valida(**overrides):
    base = {
        "nombre": "Bolso de prueba",
        "categoria": "Bolsos",
        "color": "Rosa",
        "talla_tamano": "",
        "proveedor_id": "",
        "costo": 1000,
        "precio": 2000,
        "stock_minimo": 1,
        "codigo_barras": "",
        "cantidad_inicial": 5,
    }
    base.update(overrides)
    return base


def test_validar_filas_fila_valida_no_reporta_errores(storage):
    resultado = importer.validar_filas(storage, [_fila_valida()])
    assert resultado.ok
    assert resultado.errores == []
    assert len(resultado.filas_validas) == 1


def test_validar_filas_no_escribe_nada(storage):
    importer.validar_filas(storage, [_fila_valida(), _fila_valida(nombre="")])
    assert storage.read_sheet(schema.PRODUCTOS).empty
    assert storage.transacciones_confirmadas == 0


def test_validar_filas_reporta_nombre_vacio(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(nombre="")])
    assert not resultado.ok
    assert any(e.columna == "nombre" for e in resultado.errores)
    assert resultado.filas_validas == []


def test_validar_filas_reporta_costo_con_decimales(storage):
    # "," es el separador decimal en el formato colombiano (R1: el punto es
    # de miles); con decimales distintos de cero, parse_pesos lo rechaza.
    resultado = importer.validar_filas(storage, [_fila_valida(costo="10,50")])
    assert not resultado.ok
    assert any(e.columna == "costo" for e in resultado.errores)


def test_plantilla_columnas_devuelve_copia_independiente():
    columnas_a = importer.plantilla_columnas()
    columnas_a.append("otra")
    columnas_b = importer.plantilla_columnas()
    assert "otra" not in columnas_b
    assert columnas_b == [
        "nombre",
        "categoria",
        "color",
        "talla_tamano",
        "proveedor_id",
        "costo",
        "precio",
        "stock_minimo",
        "codigo_barras",
        "cantidad_inicial",
    ]


def test_validar_filas_acepta_dataframe_con_valores_vacios(storage):
    import pandas as pd

    df = pd.DataFrame([_fila_valida()])
    df.loc[0, "talla_tamano"] = pd.NA  # celda vacía real de un Excel leído con pandas
    resultado = importer.validar_filas(storage, df)
    assert resultado.ok
    assert resultado.filas_validas[0]["talla_tamano"] == ""


def test_validar_filas_reporta_nombre_demasiado_largo(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(nombre="x" * 3000)])
    assert not resultado.ok
    assert any(e.columna == "nombre" for e in resultado.errores)


def test_validar_filas_reporta_costo_negativo(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(costo=-100)])
    assert not resultado.ok
    assert any(e.columna == "costo" for e in resultado.errores)


def test_validar_filas_reporta_precio_negativo(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(precio=-100)])
    assert not resultado.ok
    assert any(e.columna == "precio" for e in resultado.errores)


def test_validar_filas_reporta_stock_minimo_invalido(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(stock_minimo="diez")])
    assert not resultado.ok
    assert any(e.columna == "stock_minimo" for e in resultado.errores)


def test_validar_filas_reporta_codigo_barras_demasiado_largo(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(codigo_barras="X" * 3000)])
    assert not resultado.ok
    assert any(e.columna == "codigo_barras" for e in resultado.errores)


def test_validar_filas_reporta_cantidad_inicial_negativa(storage):
    # R3: el stock nunca puede quedar negativo, ni siquiera por importación.
    resultado = importer.validar_filas(storage, [_fila_valida(cantidad_inicial=-1)])
    assert not resultado.ok
    assert any(e.columna == "cantidad_inicial" for e in resultado.errores)


def test_validar_filas_precio_menor_que_costo_es_advertencia_no_error(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(costo=5000, precio=3000)])
    assert resultado.ok  # no bloquea
    assert len(resultado.advertencias) == 1


def test_validar_filas_codigo_barras_duplicado_en_el_lote(storage):
    resultado = importer.validar_filas(
        storage,
        [_fila_valida(codigo_barras="DUP-1"), _fila_valida(nombre="Otro", codigo_barras="DUP-1")],
    )
    assert not resultado.ok
    assert any(e.columna == "codigo_barras" for e in resultado.errores)


def test_validar_filas_codigo_barras_ya_existe_en_inventario(storage):
    with storage.transaction() as tx:
        import pandas as pd

        productos = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": "OT-000001",
                    "nombre": "Existente",
                    "categoria": "",
                    "color": "",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": 1000,
                    "precio": 2000,
                    "stock_minimo": 0,
                    "codigo_barras": "YA-EXISTE",
                    "activo": True,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([productos, nueva], ignore_index=True))

    resultado = importer.validar_filas(storage, [_fila_valida(codigo_barras="YA-EXISTE")])
    assert not resultado.ok
    assert any(e.columna == "codigo_barras" for e in resultado.errores)


def test_validar_filas_nombre_formula_sobrevive_intacto(storage):
    resultado = importer.validar_filas(storage, [_fila_valida(nombre="=1+1")])
    assert resultado.ok
    assert resultado.filas_validas[0]["nombre"] == "=1+1"


def test_aplicar_importacion_requiere_confirmar_true(storage):
    with pytest.raises(ValueError):
        importer.aplicar_importacion(
            storage, ADMIN, filas=[_fila_valida()], usuario_id="U-1", confirmar=False
        )
    assert storage.read_sheet(schema.PRODUCTOS).empty


def test_aplicar_importacion_con_filas_invalidas_no_escribe_nada(storage):
    with pytest.raises(ValueError):
        importer.aplicar_importacion(
            storage,
            ADMIN,
            filas=[_fila_valida(), _fila_valida(nombre="")],
            usuario_id="U-1",
            confirmar=True,
        )
    assert storage.read_sheet(schema.PRODUCTOS).empty
    assert storage.transacciones_confirmadas == 0


def test_aplicar_importacion_con_filas_validas_crea_productos_y_movimientos(storage):
    filas = [
        _fila_valida(nombre="Bolso A", cantidad_inicial=5),
        _fila_valida(nombre="Bolso B", cantidad_inicial=0),
    ]
    resumen = importer.aplicar_importacion(storage, ADMIN, filas=filas, usuario_id="U-1", confirmar=True)
    assert resumen["creados"] == 2

    productos = storage.read_sheet(schema.PRODUCTOS)
    assert len(productos) == 2
    assert set(productos["nombre"]) == {"Bolso A", "Bolso B"}

    stock_df = storage.read_sheet(schema.STOCK)
    assert len(stock_df) == 1  # solo Bolso A tenía cantidad_inicial > 0

    movimientos = storage.read_sheet(schema.MOVIMIENTOS)
    stock_inicial_movs = movimientos[movimientos["tipo"] == "stock_inicial"]
    assert len(stock_inicial_movs) == 1
    assert int(stock_inicial_movs.iloc[0]["cantidad"]) == 5


def test_vendedor_no_puede_importar_inventario(storage):
    with pytest.raises(PermisoDenegadoError):
        importer.aplicar_importacion(
            storage, VENDEDOR, filas=[_fila_valida()], usuario_id="U-2", confirmar=True
        )
    assert storage.read_sheet(schema.PRODUCTOS).empty
