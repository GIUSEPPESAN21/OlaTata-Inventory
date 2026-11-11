"""CRUD de productos, conteo físico y verificación de integridad (R3, R4).

Propiedad exclusiva de A1 (INVENTARIO). No es un contrato congelado — ver
docs/CONTRATOS.md para la lista de módulos que SÍ lo son.

Reglas aplicadas aquí:
- R3: el stock nunca queda negativo (se valida dentro de la transacción,
  con la cantidad real del momento, no solo en la UI).
- R4: toda variación de stock genera una fila en `movimientos`
  (tipo, ±cantidad, stock_antes, stock_despues, usuario, referencia).
  "Verificar integridad" recalcula stock = Σ movimientos y compara contra
  la hoja `stock`.
- R11: todo texto libre pasa por `excel_safe` antes de guardarse.
- §10: cada función que escribe o expone datos sensibles (costos) llama
  `requerir(rol, "...")` como primera línea.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core import schema
from core.excel_safe import excel_safe
from core.money import parse_pesos
from core.permissions import requerir
from core.timeutil import now_utc, to_iso_utc

__all__ = [
    "AdvertenciaProducto",
    "ResultadoConteo",
    "DiferenciaIntegridad",
    "listar_productos",
    "obtener_producto",
    "crear_producto",
    "editar_producto",
    "activar_producto",
    "desactivar_producto",
    "conteo_fisico",
    "verificar_integridad",
]

MAX_NOMBRE = 200
MAX_CATEGORIA = 100
MAX_CODIGO_BARRAS = 64


@dataclass
class AdvertenciaProducto:
    """Advertencia no bloqueante (p.ej. precio < costo)."""

    campo: str
    mensaje: str


@dataclass
class ResultadoConteo:
    producto_id: str
    stock_sistema: int
    stock_contado: int
    diferencia: int
    movimiento_id: str | None = None


@dataclass
class DiferenciaIntegridad:
    producto_id: str
    sede_id: str
    stock_en_hoja: int
    stock_recalculado: int
    diferencia: int


def _nueva_fila_movimiento(
    *,
    mov_id: str,
    ahora: str,
    producto_id: str,
    sede_id: str,
    tipo: str,
    cantidad: int,
    stock_antes: int,
    stock_despues: int,
    costo_unitario: int,
    ref_tipo: str,
    ref_id: str,
    usuario_id: str,
    nota: str,
    proveedor_id: str = "",
    documento_ref: str = "",
) -> dict:
    return {
        "id": mov_id,
        "fecha_hora_utc": ahora,
        "producto_id": producto_id,
        "sede_id": sede_id,
        "tipo": tipo,
        "cantidad": cantidad,
        "stock_antes": stock_antes,
        "stock_despues": stock_despues,
        "costo_unitario": costo_unitario,
        "ref_tipo": ref_tipo,
        "ref_id": ref_id,
        "proveedor_id": proveedor_id,
        "documento_ref": documento_ref,
        "usuario_id": usuario_id,
        "nota": nota,
        "created_at": ahora,
        "updated_at": ahora,
    }


# --------------------------------------------------------------- lectura
def listar_productos(
    storage,
    rol: str,
    *,
    categoria: str | None = None,
    bajo_minimo: bool = False,
    sin_stock: bool = False,
    busqueda: str | None = None,
    solo_activos: bool | None = None,
) -> pd.DataFrame:
    """Lista productos con filtros (categoría, bajo mínimo, sin stock) y
    búsqueda por nombre/código de barras. Incluye costo y stock actual, por
    lo que requiere la capacidad "gestionar_inventario" (la vista entera de
    inventario es admin-only por diseño, §6)."""
    requerir(rol, "gestionar_inventario")

    productos = storage.read_sheet(schema.PRODUCTOS)
    stock_df = storage.read_sheet(schema.STOCK)
    stock_total = (
        stock_df.groupby("producto_id")["cantidad"].sum() if not stock_df.empty else pd.Series(dtype="int64")
    )
    productos = productos.copy()
    productos["stock_actual"] = productos["id"].map(stock_total).fillna(0).astype(int)

    if solo_activos is not None:
        productos = productos[productos["activo"].astype(bool) == solo_activos]
    if categoria:
        productos = productos[productos["categoria"] == categoria]
    if bajo_minimo:
        minimos = pd.to_numeric(productos["stock_minimo"], errors="coerce").fillna(0)
        productos = productos[productos["stock_actual"] <= minimos]
    if sin_stock:
        productos = productos[productos["stock_actual"] <= 0]
    if busqueda:
        patron = busqueda.strip().lower()
        if patron:
            nombre_match = productos["nombre"].astype(str).str.lower().str.contains(patron, regex=False)
            codigo_match = (
                productos["codigo_barras"].astype(str).str.lower().str.contains(patron, regex=False)
            )
            productos = productos[nombre_match | codigo_match]

    return productos.reset_index(drop=True)


def obtener_producto(storage, rol: str, producto_id: str) -> pd.Series | None:
    """Un único producto por id, o None si no existe."""
    requerir(rol, "gestionar_inventario")
    productos = storage.read_sheet(schema.PRODUCTOS)
    fila = productos[productos["id"] == producto_id]
    return None if fila.empty else fila.iloc[0]


def _validar_precio_costo(precio: int, costo: int) -> list[AdvertenciaProducto]:
    advertencias: list[AdvertenciaProducto] = []
    if precio < costo:
        advertencias.append(
            AdvertenciaProducto(
                campo="precio",
                mensaje="El precio de venta es menor que el costo: esta venta daría pérdida.",
            )
        )
    return advertencias


def _codigo_barras_en_uso(productos: pd.DataFrame, codigo_barras: str, excluir_id: str | None = None) -> bool:
    if not codigo_barras:
        return False
    coincide = productos["codigo_barras"].astype(str) == codigo_barras
    if excluir_id is not None:
        coincide &= productos["id"] != excluir_id
    return bool(coincide.any())


# ------------------------------------------------------------------ CRUD
def crear_producto(
    storage,
    rol: str,
    *,
    nombre: str,
    usuario_id: str,
    categoria: str = "",
    color: str = "",
    talla_tamano: str = "",
    proveedor_id: str = "",
    costo,
    precio,
    stock_minimo: int = 0,
    codigo_barras: str = "",
    stock_inicial: int = 0,
    sede_id: str = schema.SEDE_PRINCIPAL,
) -> dict:
    """Crea un producto nuevo con id autogenerado "OT-000001" (contador
    atómico). Valida precio < costo (advertencia, no bloqueo, R: la UI
    decide si confirma) y código de barras único si se asigna. Si se da un
    `stock_inicial` > 0, registra el movimiento de apertura (R4).

    Solo admin (capacidad "gestionar_inventario", revalidada aquí).
    """
    requerir(rol, "gestionar_inventario")

    nombre_safe = excel_safe(nombre, max_length=MAX_NOMBRE, field_name="nombre")
    if not nombre_safe:
        raise ValueError("El nombre del producto no puede estar vacío.")
    categoria_safe = excel_safe(categoria or "", max_length=MAX_CATEGORIA, field_name="categoria")
    color_safe = excel_safe(color or "", max_length=MAX_CATEGORIA, field_name="color")
    talla_safe = excel_safe(talla_tamano or "", max_length=MAX_CATEGORIA, field_name="talla_tamano")
    proveedor_id_safe = excel_safe(proveedor_id or "", field_name="proveedor_id")
    codigo_barras_safe = excel_safe(
        codigo_barras or "", max_length=MAX_CODIGO_BARRAS, field_name="codigo_barras"
    )

    costo_int = parse_pesos(costo)
    precio_int = parse_pesos(precio)
    if costo_int < 0 or precio_int < 0:
        raise ValueError("El costo y el precio no pueden ser negativos.")
    stock_minimo_int = int(stock_minimo)
    if stock_minimo_int < 0:
        raise ValueError("El stock mínimo no puede ser negativo.")
    stock_inicial_int = int(stock_inicial)
    if stock_inicial_int < 0:
        raise ValueError("El stock inicial no puede ser negativo (R3: el stock nunca es negativo).")

    advertencias = _validar_precio_costo(precio_int, costo_int)

    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        if _codigo_barras_en_uso(productos, codigo_barras_safe):
            raise ValueError(f"El código de barras '{codigo_barras_safe}' ya está en uso.")

        nuevo_id = f"OT-{tx.next_counter('productos'):06d}"
        ahora = to_iso_utc(now_utc())
        nueva_fila = pd.DataFrame(
            [
                {
                    "id": nuevo_id,
                    "nombre": nombre_safe,
                    "categoria": categoria_safe,
                    "color": color_safe,
                    "talla_tamano": talla_safe,
                    "proveedor_id": proveedor_id_safe,
                    "costo": costo_int,
                    "precio": precio_int,
                    "stock_minimo": stock_minimo_int,
                    "codigo_barras": codigo_barras_safe,
                    "activo": True,
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            ]
        )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([productos, nueva_fila], ignore_index=True))

        mov_id = None
        if stock_inicial_int > 0:
            stock_df = tx.read_sheet(schema.STOCK)
            nueva_stock = pd.DataFrame(
                [
                    {
                        "producto_id": nuevo_id,
                        "sede_id": sede_id,
                        "cantidad": stock_inicial_int,
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                ]
            )
            tx.write_sheet(schema.STOCK, pd.concat([stock_df, nueva_stock], ignore_index=True))

            mov_id = f"MOV-{tx.next_counter('movimientos'):08d}"
            movimientos = tx.read_sheet(schema.MOVIMIENTOS)
            fila_mov = _nueva_fila_movimiento(
                mov_id=mov_id,
                ahora=ahora,
                producto_id=nuevo_id,
                sede_id=sede_id,
                tipo="apertura",
                cantidad=stock_inicial_int,
                stock_antes=0,
                stock_despues=stock_inicial_int,
                costo_unitario=costo_int,
                ref_tipo="creacion_producto",
                ref_id=nuevo_id,
                usuario_id=usuario_id,
                nota="Stock inicial al crear el producto.",
            )
            tx.write_sheet(schema.MOVIMIENTOS, pd.concat([movimientos, pd.DataFrame([fila_mov])], ignore_index=True))

    return {"id": nuevo_id, "advertencias": advertencias, "movimiento_id": mov_id}


def editar_producto(
    storage,
    rol: str,
    *,
    producto_id: str,
    usuario_id: str,
    nombre: str | None = None,
    categoria: str | None = None,
    color: str | None = None,
    talla_tamano: str | None = None,
    proveedor_id: str | None = None,
    costo=None,
    precio=None,
    stock_minimo: int | None = None,
    codigo_barras: str | None = None,
) -> dict:
    """Edita los campos de catálogo de un producto existente (nunca su
    stock: eso solo cambia por entrada, venta, conteo o anulación, R4).
    Solo los campos pasados (distintos de None) se actualizan.

    Solo admin (capacidad "gestionar_inventario", revalidada aquí).
    """
    requerir(rol, "gestionar_inventario")

    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        coincide = productos["id"] == producto_id
        if not coincide.any():
            raise ValueError(f"El producto '{producto_id}' no existe.")

        fila_actual = productos.loc[coincide].iloc[0]
        ahora = to_iso_utc(now_utc())

        if nombre is not None:
            nombre_safe = excel_safe(nombre, max_length=MAX_NOMBRE, field_name="nombre")
            if not nombre_safe:
                raise ValueError("El nombre del producto no puede estar vacío.")
            productos.loc[coincide, "nombre"] = nombre_safe
        if categoria is not None:
            productos.loc[coincide, "categoria"] = excel_safe(
                categoria, max_length=MAX_CATEGORIA, field_name="categoria"
            )
        if color is not None:
            productos.loc[coincide, "color"] = excel_safe(color, max_length=MAX_CATEGORIA, field_name="color")
        if talla_tamano is not None:
            productos.loc[coincide, "talla_tamano"] = excel_safe(
                talla_tamano, max_length=MAX_CATEGORIA, field_name="talla_tamano"
            )
        if proveedor_id is not None:
            productos.loc[coincide, "proveedor_id"] = excel_safe(proveedor_id, field_name="proveedor_id")

        codigo_barras_safe = str(fila_actual["codigo_barras"]) if not pd.isna(fila_actual["codigo_barras"]) else ""
        if codigo_barras is not None:
            codigo_barras_safe = excel_safe(
                codigo_barras, max_length=MAX_CODIGO_BARRAS, field_name="codigo_barras"
            )
            if _codigo_barras_en_uso(productos, codigo_barras_safe, excluir_id=producto_id):
                raise ValueError(f"El código de barras '{codigo_barras_safe}' ya está en uso.")
            productos.loc[coincide, "codigo_barras"] = codigo_barras_safe

        costo_int = int(fila_actual["costo"]) if not pd.isna(fila_actual["costo"]) else 0
        if costo is not None:
            costo_int = parse_pesos(costo)
            if costo_int < 0:
                raise ValueError("El costo no puede ser negativo.")
            productos.loc[coincide, "costo"] = costo_int

        precio_int = int(fila_actual["precio"]) if not pd.isna(fila_actual["precio"]) else 0
        if precio is not None:
            precio_int = parse_pesos(precio)
            if precio_int < 0:
                raise ValueError("El precio no puede ser negativo.")
            productos.loc[coincide, "precio"] = precio_int

        if stock_minimo is not None:
            stock_minimo_int = int(stock_minimo)
            if stock_minimo_int < 0:
                raise ValueError("El stock mínimo no puede ser negativo.")
            productos.loc[coincide, "stock_minimo"] = stock_minimo_int

        productos.loc[coincide, "updated_at"] = ahora
        tx.write_sheet(schema.PRODUCTOS, productos)

    advertencias = _validar_precio_costo(precio_int, costo_int)
    return {"id": producto_id, "advertencias": advertencias}


def _cambiar_activo(storage, rol: str, *, producto_id: str, usuario_id: str, activo: bool) -> None:
    requerir(rol, "gestionar_inventario")
    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        coincide = productos["id"] == producto_id
        if not coincide.any():
            raise ValueError(f"El producto '{producto_id}' no existe.")
        productos.loc[coincide, "activo"] = activo
        productos.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
        tx.write_sheet(schema.PRODUCTOS, productos)


def activar_producto(storage, rol: str, *, producto_id: str, usuario_id: str) -> None:
    """Reactiva un producto desactivado. Nunca se borra físicamente (R)."""
    _cambiar_activo(storage, rol, producto_id=producto_id, usuario_id=usuario_id, activo=True)


def desactivar_producto(storage, rol: str, *, producto_id: str, usuario_id: str) -> None:
    """Desactiva un producto (deja de ofrecerse) sin borrarlo físicamente."""
    _cambiar_activo(storage, rol, producto_id=producto_id, usuario_id=usuario_id, activo=False)


# --------------------------------------------------------------- conteo
def conteo_fisico(
    storage,
    rol: str,
    *,
    producto_id: str,
    cantidad_contada: int,
    usuario_id: str,
    motivo: str | None = None,
    sede_id: str = schema.SEDE_PRINCIPAL,
) -> ResultadoConteo:
    """Conteo físico: compara lo contado contra el sistema. Si hay
    diferencia, EXIGE un motivo (no vacío) y genera un movimiento
    "ajuste_conteo" que deja el stock en lo contado (R3, R4). Si no hay
    diferencia, no se escribe ningún movimiento.

    Solo admin (capacidad "ajustar_stock", revalidada aquí).
    """
    requerir(rol, "ajustar_stock")

    cantidad_contada = int(cantidad_contada)
    if cantidad_contada < 0:
        raise ValueError("La cantidad contada no puede ser negativa (R3: el stock nunca es negativo).")

    with storage.transaction() as tx:
        productos = tx.read_sheet(schema.PRODUCTOS)
        if not (productos["id"] == producto_id).any():
            raise ValueError(f"El producto '{producto_id}' no existe.")

        stock_df = tx.read_sheet(schema.STOCK)
        coincide_stock = (stock_df["producto_id"] == producto_id) & (stock_df["sede_id"] == sede_id)
        stock_sistema = int(stock_df.loc[coincide_stock, "cantidad"].iloc[0]) if coincide_stock.any() else 0

        diferencia = cantidad_contada - stock_sistema
        mov_id = None
        if diferencia != 0:
            motivo_safe = excel_safe(motivo or "", field_name="motivo")
            if not motivo_safe:
                raise ValueError(
                    "Hay una diferencia entre lo contado y el sistema: el motivo del ajuste es obligatorio."
                )

            ahora = to_iso_utc(now_utc())
            if coincide_stock.any():
                stock_df.loc[coincide_stock, "cantidad"] = cantidad_contada
                stock_df.loc[coincide_stock, "updated_at"] = ahora
            else:
                nueva_fila_stock = pd.DataFrame(
                    [
                        {
                            "producto_id": producto_id,
                            "sede_id": sede_id,
                            "cantidad": cantidad_contada,
                            "created_at": ahora,
                            "updated_at": ahora,
                        }
                    ]
                )
                stock_df = pd.concat([stock_df, nueva_fila_stock], ignore_index=True)
            tx.write_sheet(schema.STOCK, stock_df)

            mov_id = f"MOV-{tx.next_counter('movimientos'):08d}"
            movimientos = tx.read_sheet(schema.MOVIMIENTOS)
            fila_mov = _nueva_fila_movimiento(
                mov_id=mov_id,
                ahora=ahora,
                producto_id=producto_id,
                sede_id=sede_id,
                tipo="ajuste_conteo",
                cantidad=diferencia,
                stock_antes=stock_sistema,
                stock_despues=cantidad_contada,
                costo_unitario=0,
                ref_tipo="conteo_fisico",
                ref_id=mov_id,
                usuario_id=usuario_id,
                nota=motivo_safe,
            )
            tx.write_sheet(
                schema.MOVIMIENTOS, pd.concat([movimientos, pd.DataFrame([fila_mov])], ignore_index=True)
            )

    return ResultadoConteo(
        producto_id=producto_id,
        stock_sistema=stock_sistema,
        stock_contado=cantidad_contada,
        diferencia=diferencia,
        movimiento_id=mov_id,
    )


# ----------------------------------------------------------- integridad
def verificar_integridad(storage, rol: str, *, sede_id: str | None = None) -> list[DiferenciaIntegridad]:
    """Recalcula, para cada producto (y sede), el stock como la suma de sus
    movimientos (R4: invariante stock = Σ movimientos) y lo compara contra
    la hoja `stock`. Devuelve solo las diferencias encontradas.

    Solo admin (capacidad "verificar_integridad", revalidada aquí).
    """
    requerir(rol, "verificar_integridad")

    stock_df = storage.read_sheet(schema.STOCK)
    movimientos = storage.read_sheet(schema.MOVIMIENTOS)

    if sede_id is not None:
        stock_df = stock_df[stock_df["sede_id"] == sede_id]
        movimientos = movimientos[movimientos["sede_id"] == sede_id]

    stock_df = stock_df.copy()
    stock_df["cantidad"] = pd.to_numeric(stock_df["cantidad"], errors="coerce").fillna(0).astype(int)
    en_hoja = {
        (str(fila["producto_id"]), str(fila["sede_id"])): int(fila["cantidad"])
        for _, fila in stock_df.iterrows()
    }

    movimientos = movimientos.copy()
    movimientos["cantidad"] = pd.to_numeric(movimientos["cantidad"], errors="coerce").fillna(0).astype(int)
    recalculado: dict[tuple[str, str], int] = {}
    if not movimientos.empty:
        agrupado = movimientos.groupby(["producto_id", "sede_id"])["cantidad"].sum()
        for (producto_id, sede), total in agrupado.items():
            recalculado[(str(producto_id), str(sede))] = int(total)

    claves = set(en_hoja) | set(recalculado)
    diferencias: list[DiferenciaIntegridad] = []
    for producto_id, sede in sorted(claves):
        valor_hoja = en_hoja.get((producto_id, sede), 0)
        valor_recalculado = recalculado.get((producto_id, sede), 0)
        if valor_hoja != valor_recalculado:
            diferencias.append(
                DiferenciaIntegridad(
                    producto_id=producto_id,
                    sede_id=sede,
                    stock_en_hoja=valor_hoja,
                    stock_recalculado=valor_recalculado,
                    diferencia=valor_hoja - valor_recalculado,
                )
            )
    return diferencias
