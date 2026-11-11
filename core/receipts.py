"""Texto del recibo y enlace de WhatsApp con mensaje prellenado.
Propiedad de A2 (VENTAS).

SIN API de WhatsApp (R: solo un enlace `https://wa.me/...` que el
vendedor abre manualmente desde la pantalla de Vender).
"""
from __future__ import annotations

from urllib.parse import quote

from core.money import format_cop

__all__ = ["TELEFONO_PLACEHOLDER", "generar_texto_recibo", "generar_url_whatsapp"]

# Número ficticio de prueba (NUNCA un número real); se usa solo si no hay
# `telefono_whatsapp` configurado en CONFIG.
TELEFONO_PLACEHOLDER = "573000000000"

NOMBRE_NEGOCIO = "Ola Tata · Bolsos y Accesorios"


def _obtener(obj, clave: str):
    return obj[clave] if isinstance(obj, dict) else getattr(obj, clave)


def _solo_digitos(telefono: str) -> str:
    return "".join(ch for ch in telefono if ch.isdigit())


def generar_texto_recibo(venta) -> str:
    """`venta` es un `core.sales.Venta` (o cualquier objeto/dict con los
    mismos atributos/claves: numero, fecha_local, items, pagos, subtotal,
    descuento_total, envio_cobrado, total, cliente_nombre)."""
    lineas = [
        NOMBRE_NEGOCIO,
        f"Venta {_obtener(venta, 'numero')}  ·  {_obtener(venta, 'fecha_local')}",
        "-" * 32,
    ]
    for item in _obtener(venta, "items"):
        nombre = _obtener(item, "nombre_snapshot")
        cantidad = int(_obtener(item, "cantidad"))
        total_linea = int(_obtener(item, "total_linea"))
        lineas.append(f"{cantidad} x {nombre}  ->  {format_cop(total_linea)}")

    lineas.append("-" * 32)
    lineas.append(f"Subtotal: {format_cop(int(_obtener(venta, 'subtotal')))}")

    descuento_total = int(_obtener(venta, "descuento_total"))
    if descuento_total:
        lineas.append(f"Descuento: -{format_cop(descuento_total)}")

    envio_cobrado = int(_obtener(venta, "envio_cobrado"))
    if envio_cobrado:
        lineas.append(f"Envío: {format_cop(envio_cobrado)}")

    lineas.append(f"TOTAL: {format_cop(int(_obtener(venta, 'total')))}")

    for pago in _obtener(venta, "pagos"):
        metodo = _obtener(pago, "metodo")
        monto = int(_obtener(pago, "monto"))
        lineas.append(f"Pago ({metodo}): {format_cop(monto)}")

    cliente_nombre = _obtener(venta, "cliente_nombre")
    if cliente_nombre:
        lineas.append(f"Cliente: {cliente_nombre}")

    lineas.append("¡Gracias por tu compra!")
    return "\n".join(lineas)


def generar_url_whatsapp(venta, telefono_whatsapp: str | None = None) -> str:
    """URL `https://wa.me/<telefono>?text=<recibo prellenado>`.

    `telefono_whatsapp` normalmente viene de `storage.get_config(...)`
    (configuración del negocio); si no se provee, usa un número ficticio
    de prueba (`TELEFONO_PLACEHOLDER`)."""
    telefono = _solo_digitos(telefono_whatsapp or TELEFONO_PLACEHOLDER)
    if not telefono:
        telefono = TELEFONO_PLACEHOLDER
    texto = generar_texto_recibo(venta)
    return f"https://wa.me/{telefono}?text={quote(texto)}"
