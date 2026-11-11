"""Importación de inventario inicial desde Excel/CSV (R3, R4, R11).

Propiedad exclusiva de A1 (INVENTARIO). No es un contrato congelado — ver
docs/CONTRATOS.md para la lista de módulos que SÍ lo son.

Flujo en dos pasos, obligatorio:
1. `validar_filas(...)` — SIN escribir nada. Devuelve un `ResultadoValidacion`
   con un error por fila/columna inválida y la lista de filas ya normalizadas
   que sí se podrían aplicar. La vista muestra esta vista previa.
2. `aplicar_importacion(...)` — solo si el usuario confirma explícitamente
   (`confirmar=True`). Vuelve a validar (defensa en profundidad, R3) y, si
   no hay errores, crea cada producto + su movimiento "stock_inicial" dentro
   de UNA transacción atómica.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core import schema
from core.excel_safe import excel_safe
from core.money import DineroInvalidoError, parse_pesos
from core.permissions import requerir
from core.timeutil import now_utc, to_iso_utc

__all__ = [
    "ErrorFila",
    "ResultadoValidacion",
    "COLUMNAS_PLANTILLA",
    "plantilla_columnas",
    "validar_filas",
    "aplicar_importacion",
]

MAX_NOMBRE = 200
MAX_CATEGORIA = 100
MAX_CODIGO_BARRAS = 64

# Columnas de la plantilla descargable. "nombre", "costo" y "precio" son
# obligatorias; el resto es opcional (se normaliza a "" / 0 si falta).
COLUMNAS_PLANTILLA: list[str] = [
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


@dataclass
class ErrorFila:
    """Un problema en una fila concreta de la importación (fila 1-based,
    sin contar el encabezado) — para mostrarlo tal cual en la vista previa."""

    fila: int
    columna: str
    mensaje: str


@dataclass
class ResultadoValidacion:
    errores: list[ErrorFila] = field(default_factory=list)
    advertencias: list[ErrorFila] = field(default_factory=list)
    filas_validas: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores


def plantilla_columnas() -> list[str]:
    """Copia de las columnas de la plantilla descargable."""
    return list(COLUMNAS_PLANTILLA)


def _a_lista_de_dicts(filas) -> list[dict]:
    if isinstance(filas, pd.DataFrame):
        return [dict(fila) for _, fila in filas.iterrows()]
    return [dict(fila) for fila in filas]


def _valor_o_vacio(fila: dict, clave: str) -> object:
    valor = fila.get(clave)
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return valor


def validar_filas(storage, filas) -> ResultadoValidacion:
    """Valida fila por fila SIN escribir nada. `filas`: lista de dicts o un
    `pandas.DataFrame` con (al menos) las columnas de `COLUMNAS_PLANTILLA`.

    Por fila reporta todos los errores encontrados (no solo el primero),
    para que la vista previa los liste completos antes de que el usuario
    decida importar. El código de barras debe ser único dentro del lote Y
    frente a los productos ya existentes.
    """
    productos_existentes = storage.read_sheet(schema.PRODUCTOS)
    codigos_existentes = {
        str(c) for c in productos_existentes["codigo_barras"].dropna().astype(str) if c
    }

    resultado = ResultadoValidacion()
    codigos_en_lote: dict[str, int] = {}

    for indice, fila_cruda in enumerate(_a_lista_de_dicts(filas), start=1):
        errores_fila: list[ErrorFila] = []
        advertencias_fila: list[ErrorFila] = []

        nombre_crudo = _valor_o_vacio(fila_cruda, "nombre")
        try:
            nombre = excel_safe(str(nombre_crudo), max_length=MAX_NOMBRE, field_name="nombre")
        except Exception as exc:
            nombre = ""
            errores_fila.append(ErrorFila(indice, "nombre", str(exc)))
        if not nombre:
            errores_fila.append(ErrorFila(indice, "nombre", "El nombre es obligatorio."))

        costo = None
        costo_crudo = _valor_o_vacio(fila_cruda, "costo")
        try:
            costo = parse_pesos(costo_crudo if costo_crudo != "" else 0)
            if costo < 0:
                raise DineroInvalidoError("El costo no puede ser negativo.")
        except DineroInvalidoError as exc:
            errores_fila.append(ErrorFila(indice, "costo", str(exc)))

        precio = None
        precio_crudo = _valor_o_vacio(fila_cruda, "precio")
        try:
            precio = parse_pesos(precio_crudo if precio_crudo != "" else 0)
            if precio < 0:
                raise DineroInvalidoError("El precio no puede ser negativo.")
        except DineroInvalidoError as exc:
            errores_fila.append(ErrorFila(indice, "precio", str(exc)))

        if costo is not None and precio is not None and precio < costo:
            advertencias_fila.append(
                ErrorFila(indice, "precio", "El precio es menor que el costo: esta fila dará pérdida.")
            )

        stock_minimo = 0
        stock_minimo_crudo = _valor_o_vacio(fila_cruda, "stock_minimo")
        try:
            stock_minimo = int(float(stock_minimo_crudo)) if stock_minimo_crudo != "" else 0
            if stock_minimo < 0:
                raise ValueError
        except (TypeError, ValueError):
            errores_fila.append(ErrorFila(indice, "stock_minimo", "El stock mínimo debe ser un entero >= 0."))

        cantidad_inicial = 0
        cantidad_crudo = _valor_o_vacio(fila_cruda, "cantidad_inicial")
        try:
            cantidad_inicial = int(float(cantidad_crudo)) if cantidad_crudo != "" else 0
            if cantidad_inicial < 0:
                raise ValueError
        except (TypeError, ValueError):
            errores_fila.append(
                ErrorFila(
                    indice,
                    "cantidad_inicial",
                    "La cantidad inicial debe ser un entero >= 0 (R3: el stock nunca es negativo).",
                )
            )

        try:
            codigo_barras = excel_safe(
                str(_valor_o_vacio(fila_cruda, "codigo_barras")),
                max_length=MAX_CODIGO_BARRAS,
                field_name="codigo_barras",
            )
        except Exception as exc:
            codigo_barras = ""
            errores_fila.append(ErrorFila(indice, "codigo_barras", str(exc)))

        if codigo_barras:
            if codigo_barras in codigos_existentes:
                errores_fila.append(
                    ErrorFila(
                        indice, "codigo_barras", f"El código de barras '{codigo_barras}' ya existe en inventario."
                    )
                )
            elif codigo_barras in codigos_en_lote:
                errores_fila.append(
                    ErrorFila(
                        indice,
                        "codigo_barras",
                        f"El código de barras '{codigo_barras}' se repite en la fila {codigos_en_lote[codigo_barras]}.",
                    )
                )
            else:
                codigos_en_lote[codigo_barras] = indice

        categoria = excel_safe(
            str(_valor_o_vacio(fila_cruda, "categoria")), max_length=MAX_CATEGORIA, field_name="categoria"
        )
        color = excel_safe(str(_valor_o_vacio(fila_cruda, "color")), max_length=MAX_CATEGORIA, field_name="color")
        talla_tamano = excel_safe(
            str(_valor_o_vacio(fila_cruda, "talla_tamano")), max_length=MAX_CATEGORIA, field_name="talla_tamano"
        )
        proveedor_id = excel_safe(str(_valor_o_vacio(fila_cruda, "proveedor_id")), field_name="proveedor_id")

        resultado.errores.extend(errores_fila)
        resultado.advertencias.extend(advertencias_fila)
        if not errores_fila:
            resultado.filas_validas.append(
                {
                    "fila": indice,
                    "nombre": nombre,
                    "categoria": categoria,
                    "color": color,
                    "talla_tamano": talla_tamano,
                    "proveedor_id": proveedor_id,
                    "costo": costo,
                    "precio": precio,
                    "stock_minimo": stock_minimo,
                    "codigo_barras": codigo_barras,
                    "cantidad_inicial": cantidad_inicial,
                }
            )

    return resultado


def aplicar_importacion(
    storage,
    rol: str,
    *,
    filas,
    usuario_id: str,
    confirmar: bool,
    sede_id: str = schema.SEDE_PRINCIPAL,
) -> dict:
    """Aplica la importación SOLO si `confirmar=True` y no hay errores (se
    vuelve a validar aquí, defensa en profundidad — R3). Crea cada producto
    con id autogenerado y, si trae `cantidad_inicial` > 0, su movimiento
    "stock_inicial" (R4), todo en UNA transacción atómica.

    Solo admin (capacidad "importar_inventario", revalidada aquí).
    """
    requerir(rol, "importar_inventario")

    if not confirmar:
        raise ValueError("La importación requiere confirmación explícita antes de escribir nada.")

    resultado = validar_filas(storage, filas)
    if not resultado.ok:
        raise ValueError(
            f"La importación tiene {len(resultado.errores)} error(es); no se escribió nada. "
            "Corrige la vista previa y vuelve a intentar."
        )

    ids_creados: list[str] = []
    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        stock_df = tx.read_sheet(schema.STOCK)
        movimientos = tx.read_sheet(schema.MOVIMIENTOS)
        ahora = to_iso_utc(now_utc())

        nuevas_filas_productos = []
        nuevas_filas_stock = []
        nuevas_filas_movimientos = []

        for fila in resultado.filas_validas:
            nuevo_id = f"OT-{tx.next_counter('productos'):06d}"
            ids_creados.append(nuevo_id)
            nuevas_filas_productos.append(
                {
                    "id": nuevo_id,
                    "nombre": fila["nombre"],
                    "categoria": fila["categoria"],
                    "color": fila["color"],
                    "talla_tamano": fila["talla_tamano"],
                    "proveedor_id": fila["proveedor_id"],
                    "costo": fila["costo"],
                    "precio": fila["precio"],
                    "stock_minimo": fila["stock_minimo"],
                    "codigo_barras": fila["codigo_barras"],
                    "activo": True,
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )

            if fila["cantidad_inicial"] > 0:
                nuevas_filas_stock.append(
                    {
                        "producto_id": nuevo_id,
                        "sede_id": sede_id,
                        "cantidad": fila["cantidad_inicial"],
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )
                mov_id = f"MOV-{tx.next_counter('movimientos'):08d}"
                nuevas_filas_movimientos.append(
                    {
                        "id": mov_id,
                        "fecha_hora_utc": ahora,
                        "producto_id": nuevo_id,
                        "sede_id": sede_id,
                        "tipo": "stock_inicial",
                        "cantidad": fila["cantidad_inicial"],
                        "stock_antes": 0,
                        "stock_despues": fila["cantidad_inicial"],
                        "costo_unitario": fila["costo"],
                        "ref_tipo": "importacion_inicial",
                        "ref_id": nuevo_id,
                        "proveedor_id": "",
                        "documento_ref": "",
                        "usuario_id": usuario_id,
                        "nota": "Importación de inventario inicial.",
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )

        if nuevas_filas_productos:
            tx.write_sheet(schema.PRODUCTOS, pd.concat([productos, pd.DataFrame(nuevas_filas_productos)], ignore_index=True))
        if nuevas_filas_stock:
            tx.write_sheet(schema.STOCK, pd.concat([stock_df, pd.DataFrame(nuevas_filas_stock)], ignore_index=True))
        if nuevas_filas_movimientos:
            tx.write_sheet(
                schema.MOVIMIENTOS, pd.concat([movimientos, pd.DataFrame(nuevas_filas_movimientos)], ignore_index=True)
            )

    return {"creados": len(ids_creados), "ids": ids_creados, "advertencias": resultado.advertencias}
