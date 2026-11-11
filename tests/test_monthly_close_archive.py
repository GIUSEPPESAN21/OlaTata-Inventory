"""Pruebas de `core/archive.py`: construcción/lectura del .xlsx de un
cierre y mantenimiento de `cierres/INDEX.json`."""
from __future__ import annotations

import json

import pandas as pd

from core import archive


def _hojas_ejemplo() -> dict[str, pd.DataFrame]:
    return {
        "ventas": pd.DataFrame(
            [
                {"id": "V-1", "total": 27000, "nota": "=1+1"},
                {"id": "V-2", "total": 9000, "nota": "@SUM(1)"},
            ]
        ),
        "stock_cierre": pd.DataFrame([{"producto_id": "P1", "cantidad": 7, "costo": 1000, "valor": 7000}]),
    }


def test_sha256_bytes_es_estable_y_cambia_con_el_contenido():
    a = archive.sha256_bytes(b"hola")
    b = archive.sha256_bytes(b"hola")
    c = archive.sha256_bytes(b"chao")
    assert a == b
    assert a != c
    assert len(a) == 64  # hex de 32 bytes


def test_construir_y_leer_libro_cierre_round_trip():
    hojas = _hojas_ejemplo()
    contenido = archive.construir_libro_cierre(hojas)
    assert isinstance(contenido, bytes)
    leidas = archive.leer_libro_cierre(contenido)
    assert set(leidas) == set(hojas)
    assert len(leidas["ventas"]) == 2
    assert len(leidas["stock_cierre"]) == 1
    assert int(leidas["stock_cierre"].iloc[0]["valor"]) == 7000


def test_texto_que_empieza_con_igual_o_arroba_nunca_se_guarda_como_formula():
    hojas = _hojas_ejemplo()
    contenido = archive.construir_libro_cierre(hojas)
    leidas = archive.leer_libro_cierre(contenido)
    assert leidas["ventas"].iloc[0]["nota"] == "=1+1"
    assert leidas["ventas"].iloc[1]["nota"] == "@SUM(1)"


def test_libro_vacio_produce_hojas_vacias_pero_con_columnas():
    hojas = {"ventas": pd.DataFrame(columns=["id", "total"])}
    contenido = archive.construir_libro_cierre(hojas)
    leidas = archive.leer_libro_cierre(contenido)
    assert list(leidas["ventas"].columns) == ["id", "total"]
    assert len(leidas["ventas"]) == 0


def test_leer_index_sin_contenido_devuelve_estructura_vacia():
    assert archive.leer_index(None) == {"cierres": []}
    assert archive.leer_index(b"") == {"cierres": []}


def test_leer_index_parsea_json_existente():
    original = {"cierres": [{"archivo": "2026-01.xlsx", "filas_por_hoja": {}, "sha256": "x"}]}
    contenido = json.dumps(original).encode("utf-8")
    assert archive.leer_index(contenido) == original


def test_serializar_index_es_json_valido_y_legible():
    index = {"cierres": []}
    contenido = archive.serializar_index(index)
    assert json.loads(contenido.decode("utf-8")) == index


def test_construir_entrada_index_cuenta_filas_por_hoja():
    hojas = _hojas_ejemplo()
    entrada = archive.construir_entrada_index("2026-01.xlsx", hojas, "sha-abc")
    assert entrada["archivo"] == "2026-01.xlsx"
    assert entrada["filas_por_hoja"] == {"ventas": 2, "stock_cierre": 1}
    assert entrada["sha256"] == "sha-abc"
    assert "publicado_at" in entrada


def test_actualizar_index_agrega_entrada_nueva():
    index = {"cierres": []}
    entrada = archive.construir_entrada_index("2026-01.xlsx", _hojas_ejemplo(), "sha-1")
    nuevo = archive.actualizar_index(index, entrada)
    assert len(nuevo["cierres"]) == 1
    assert nuevo["cierres"][0]["archivo"] == "2026-01.xlsx"


def test_actualizar_index_reemplaza_en_vez_de_duplicar():
    index = {"cierres": []}
    entrada_1 = archive.construir_entrada_index("2026-01.xlsx", _hojas_ejemplo(), "sha-1")
    index = archive.actualizar_index(index, entrada_1)

    # Reintento tras una caída: se publica otra vez el MISMO mes.
    entrada_2 = archive.construir_entrada_index("2026-01.xlsx", _hojas_ejemplo(), "sha-2")
    index = archive.actualizar_index(index, entrada_2)

    assert len(index["cierres"]) == 1  # nunca duplica la fila del mismo archivo
    assert index["cierres"][0]["sha256"] == "sha-2"  # se queda con la versión más reciente


def test_actualizar_index_mantiene_entradas_de_otros_meses():
    index = {"cierres": []}
    index = archive.actualizar_index(index, archive.construir_entrada_index("2026-01.xlsx", _hojas_ejemplo(), "sha-1"))
    index = archive.actualizar_index(index, archive.construir_entrada_index("2026-02.xlsx", _hojas_ejemplo(), "sha-2"))
    archivos = sorted(c["archivo"] for c in index["cierres"])
    assert archivos == ["2026-01.xlsx", "2026-02.xlsx"]
