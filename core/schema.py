"""Esquema de datos de Ola Tata: una hoja de Excel por tabla.

CONTRATO CONGELADO — ver docs/CONTRATOS.md. Solo el agente principal
modifica este archivo. Si un módulo necesita una columna nueva, debe
pedirlo en su informe final en vez de editar este archivo directamente.

Todas las hojas incluyen ``id`` (o su equivalente de clave) y
``created_at``/``updated_at`` en ISO-8601 UTC con offset (ver
``core/timeutil.py``).
"""
from __future__ import annotations

PRODUCTOS = "productos"
STOCK = "stock"
MOVIMIENTOS = "movimientos"
VENTAS = "ventas"
VENTA_ITEMS = "venta_items"
PAGOS = "pagos"
DEVOLUCIONES = "devoluciones"
DEVOLUCION_ITEMS = "devolucion_items"
PROVEEDORES = "proveedores"
CUADRE_CAJA = "cuadre_caja"
USUARIOS = "usuarios"
CONFIG = "config"
AUDITORIA = "auditoria"

SHEET_NAMES: list[str] = [
    PRODUCTOS,
    STOCK,
    MOVIMIENTOS,
    VENTAS,
    VENTA_ITEMS,
    PAGOS,
    DEVOLUCIONES,
    DEVOLUCION_ITEMS,
    PROVEEDORES,
    CUADRE_CAJA,
    USUARIOS,
    CONFIG,
    AUDITORIA,
]

# Hojas que viajan en el libro vivo (OlaTata-Database) y que el cierre de
# mes archiva y vacía. STOCK, PRODUCTOS, PROVEEDORES, USUARIOS, CONFIG y
# AUDITORIA nunca se vacían (son catálogo/estado, no histórico mensual).
HOJAS_TRANSACCIONALES_MENSUALES: list[str] = [
    VENTAS,
    VENTA_ITEMS,
    PAGOS,
    DEVOLUCIONES,
    DEVOLUCION_ITEMS,
    MOVIMIENTOS,
    CUADRE_CAJA,
]

SHEET_COLUMNS: dict[str, list[str]] = {
    PRODUCTOS: [
        "id",
        "nombre",
        "categoria",
        "color",
        "talla_tamano",
        "proveedor_id",
        "costo",
        "precio",
        "stock_minimo",
        "codigo_barras",
        "activo",
        "created_at",
        "updated_at",
    ],
    STOCK: [
        "producto_id",
        "sede_id",
        "cantidad",
        "created_at",
        "updated_at",
    ],
    MOVIMIENTOS: [
        "id",
        "fecha_hora_utc",
        "producto_id",
        "sede_id",
        "tipo",
        "cantidad",
        "stock_antes",
        "stock_despues",
        "costo_unitario",
        "ref_tipo",
        "ref_id",
        "proveedor_id",
        "documento_ref",
        "usuario_id",
        "nota",
        "created_at",
        "updated_at",
    ],
    VENTAS: [
        "id",
        "numero",
        "fecha_hora_utc",
        "fecha_local",
        "sede_id",
        "canal",
        "cliente_nombre",
        "cliente_telefono",
        "subtotal",
        "descuento_total",
        "envio_cobrado",
        "envio_ciudad",
        "envio_transportadora",
        "envio_guia",
        "total",
        "estado",
        "anulada_por",
        "anulada_motivo",
        "anulada_at",
        "vendedor_id",
        "vendedor_nombre",
        "idempotency_key",
        "nota",
        "created_at",
        "updated_at",
    ],
    VENTA_ITEMS: [
        "id",
        "venta_id",
        "producto_id",
        "nombre_snapshot",
        "cantidad",
        "precio_unitario",
        "descuento_linea",
        "costo_unitario",
        "total_linea",
        "created_at",
        "updated_at",
    ],
    PAGOS: [
        "id",
        "venta_id",
        "metodo",
        "monto",
        "referencia",
        "fecha_hora_utc",
        "created_at",
        "updated_at",
    ],
    DEVOLUCIONES: [
        "id",
        "numero",
        "venta_numero",
        "fecha_hora_utc",
        "fecha_local",
        "tipo",
        "motivo",
        "reembolso_metodo",
        "reembolso_monto",
        "usuario_id",
        "created_at",
        "updated_at",
    ],
    DEVOLUCION_ITEMS: [
        "id",
        "devolucion_id",
        "producto_id",
        "nombre_snapshot",
        "cantidad",
        "precio_unitario",
        "costo_unitario",
        "destino",
        "created_at",
        "updated_at",
    ],
    PROVEEDORES: [
        "id",
        "nombre",
        "telefono",
        "ciudad",
        "notas",
        "created_at",
        "updated_at",
    ],
    CUADRE_CAJA: [
        "id",
        "fecha_local",
        "sede_id",
        "base_inicial",
        "efectivo_esperado",
        "efectivo_contado",
        "diferencia",
        "nota",
        "usuario_id",
        "created_at",
        "updated_at",
    ],
    USUARIOS: [
        "id",
        "nombre",
        "usuario",
        "password_hash",
        "rol",
        "activo",
        "must_change_password",
        "session_epoch",
        "created_at",
        "updated_at",
    ],
    CONFIG: [
        "clave",
        "valor",
        "created_at",
        "updated_at",
    ],
    AUDITORIA: [
        "id",
        "ts",
        "usuario",
        "accion",
        "detalle",
        "created_at",
        "updated_at",
    ],
}

# Tipos de movimiento válidos (R4, §5).
TIPOS_MOVIMIENTO = {
    "apertura",
    "stock_inicial",
    "entrada",
    "venta",
    "devolucion",
    "anulacion",
    "ajuste_conteo",
    "ajuste_manual",
    "merma",
}

# Estados válidos de una venta (R9).
ESTADOS_VENTA = {"completada", "anulada"}

# Métodos de pago válidos (R8).
METODOS_PAGO = {
    "efectivo",
    "datafono",
    "transferencia",
    "sistecredito",
    "cambio",
}

CANALES_VENTA = {"tienda", "instagram", "whatsapp"}

ROLES = {"admin", "vendedor"}

SEDE_PRINCIPAL = "principal"


def columnas(sheet: str) -> list[str]:
    """Devuelve una copia de la lista de columnas de una hoja."""
    return list(SHEET_COLUMNS[sheet])
