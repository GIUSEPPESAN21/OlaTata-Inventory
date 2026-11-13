"""Configuración inicial del negocio (valores por defecto de la hoja CONFIG).

Única fuente de verdad de lo que `scripts/seed_db.py` siembra y de lo que
la app restaura sola si falta (`completar_config_faltante`). Así, si la
base en la nube pierde claves (como pasó en producción cuando un
reinicio del servidor publicó un libro vacío), basta con abrir la app
para recuperarlas — sin pisar NUNCA un valor que el dueño ya editó.
"""
from __future__ import annotations

from core import schema
from core.excel_safe import excel_safe

__all__ = [
    "CATEGORIAS_INICIALES",
    "MENSAJE_RECIBO",
    "VALORES_CONFIG_INICIALES",
    "claves_faltantes",
    "completar_config_faltante",
]

_SEP = "|"

CATEGORIAS_INICIALES = [
    "Bolsos",
    "Carteras",
    "Mochilas",
    "Billeteras",
    "Cosmetiqueros",
    "Canguros",
    "Correas y cinturones",
    "Bisutería",
    "Accesorios para el cabello",
    "Gafas",
    "Otros",
]

MENSAJE_RECIBO = (
    "¡Gracias por tu compra en Ola Tata! Síguenos en Instagram @olatata_1. "
    "Cambios con este recibo."
)

VALORES_CONFIG_INICIALES: dict[str, str] = {
    "negocio_nombre": "Ola Tata · Bolsos & Accesorios",
    "negocio_whatsapp": "573173003526",
    "telefono_whatsapp": "573173003526",
    "negocio_mensaje_recibo": MENSAJE_RECIBO,
    "negocio_categorias": _SEP.join(CATEGORIAS_INICIALES),
    "negocio_metodos_pago_activos": _SEP.join(sorted(schema.METODOS_PAGO)),
    "sesion_minutos": "480",
    "permitir_vender_sin_stock": "false",
    "instagram": "@olatata_1",
    "ciudades": "Buga, Tuluá",
    "zona_horaria": "America/Bogota",
    "moneda": "COP",
}


def claves_faltantes(storage) -> list[str]:
    """Claves por defecto que hoy NO existen en CONFIG (lectura pura)."""
    df = storage.read_sheet(schema.CONFIG)
    presentes = set(df["clave"].dropna().astype(str))
    return [clave for clave in VALORES_CONFIG_INICIALES if clave not in presentes]


def completar_config_faltante(tx) -> list[str]:
    """Dentro de `storage.transaction()`: agrega SOLO las claves que
    faltan, con su valor por defecto. Devuelve las claves agregadas."""
    faltan = claves_faltantes(tx)
    for clave in faltan:
        tx.set_config(clave, excel_safe(VALORES_CONFIG_INICIALES[clave], max_length=4000, field_name=clave))
    return faltan
