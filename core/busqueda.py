"""Búsqueda de productos para Vender (en tiempo real) y Ventas.

- `buscar_productos`: coincidencia por palabras (en cualquier orden), sin
  importar mayúsculas ni tildes, sobre nombre, categoría, color, id,
  código de barras y código interno de la etiqueta. Ordena primero los
  que EMPIEZAN por lo escrito.
- `producto_por_codigo`: coincidencia EXACTA por código (lo que "teclea"
  el lector USB): código de barras propio, código interno "20xxxxxx" o id
  "OT-000123" (también "OT'000123" por el teclado latinoamericano).
Funciones puras (sin Streamlit ni `storage`).
"""
from __future__ import annotations

import unicodedata

import pandas as pd

from core.etiquetas import codigo_para_producto, id_desde_codigo_interno, normalizar_lectura_escaner

__all__ = ["normalizar", "buscar_productos", "producto_por_codigo", "stock_por_producto"]


def normalizar(texto: object) -> str:
    """minúsculas, sin tildes ni espacios repetidos ("Bísutería" -> "bisuteria")."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    sin_tildes = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def _texto(valor: object) -> str:
    return "" if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else str(valor)


def _indice(fila: pd.Series) -> str:
    codigo = codigo_para_producto(str(fila["id"]), _texto(fila.get("codigo_barras")))
    partes = [fila.get("nombre"), fila.get("categoria"), fila.get("color"), fila.get("id"), fila.get("codigo_barras"), codigo]
    return normalizar(" ".join(_texto(p) for p in partes))


def buscar_productos(productos: pd.DataFrame, texto: str, limite: int = 8) -> pd.DataFrame:
    consulta = normalizar(normalizar_lectura_escaner(texto))
    if not consulta or productos.empty:
        return productos.iloc[0:0]
    palabras = consulta.split()
    indices = productos.apply(_indice, axis=1)
    coincide = indices.apply(lambda idx: all(p in idx for p in palabras))
    encontrados = productos[coincide].copy()
    if encontrados.empty:
        return encontrados
    nombres = encontrados["nombre"].map(normalizar)
    encontrados["_orden"] = (~nombres.str.startswith(consulta)).astype(int)
    encontrados["_nombre"] = nombres
    return encontrados.sort_values(["_orden", "_nombre"]).drop(columns=["_orden", "_nombre"]).head(limite)


def producto_por_codigo(productos: pd.DataFrame, texto: str) -> pd.Series | None:
    leido = normalizar_lectura_escaner(texto)
    if not leido or productos.empty:
        return None
    codigos = productos["codigo_barras"].map(_texto).str.strip()
    por_codigo = productos[codigos == leido]
    if not por_codigo.empty:
        return por_codigo.iloc[0]
    buscado = id_desde_codigo_interno(leido) or leido.upper()
    por_id = productos[productos["id"].astype(str).str.upper() == buscado]
    if not por_id.empty:
        return por_id.iloc[0]
    return None


def stock_por_producto(stock: pd.DataFrame) -> dict[str, int]:
    """{producto_id: unidades} sumando todas las sedes."""
    if stock.empty:
        return {}
    cantidades = pd.to_numeric(stock["cantidad"], errors="coerce").fillna(0).astype(int)
    return cantidades.groupby(stock["producto_id"].astype(str)).sum().to_dict()
