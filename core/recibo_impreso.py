"""Recibo para la impresora térmica de tirilla (DigitalPOS, 80 mm, con
cortador automático) — la impresora de arriba en la foto del local.

Se genera un PDF de 80 mm de ancho y alto variable (lo que mida la venta),
en blanco y negro puro a 203 dpi, con el área imprimible típica de 72 mm.
El navegador lo imprime con el driver de la tirilla (papel "80 mm" /
"Roll paper 80 × 297 mm", escala 100 %); el cortador corta al final.

Mismo contenido que `core.receipts.generar_texto_recibo` (que se usa
para WhatsApp), pero maquetado: logo, nombre del negocio, ítems con
precio a la derecha, totales en negrita, métodos de pago legibles y el
mensaje configurable del recibo. Sin Streamlit ni `storage`.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.money import format_cop

__all__ = ["ANCHOS_PAPEL_MM", "generar_imagen_recibo", "generar_pdf_recibo"]

_RAIZ = Path(__file__).resolve().parent.parent
_FUENTE_BOLD = _RAIZ / "assets" / "fonts" / "inter-bold.otf"
_FUENTE_SEMI = _RAIZ / "assets" / "fonts" / "inter-semibold.otf"
_LOGO = _RAIZ / "assets" / "brand" / "olatata-logo-mono.png"

DPI = 203
# ancho del papel -> ancho imprimible (mm), valores estándar de tirilla
ANCHOS_PAPEL_MM = {80: 72, 58: 48}

_METODOS = {
    "efectivo": "Efectivo",
    "datafono": "Datáfono",
    "transferencia": "Transferencia",
    "sistecredito": "Sistecrédito",
    "cambio": "Cambio (saldo a favor)",
}
_CANALES = {"tienda": "Tienda", "instagram": "Instagram", "whatsapp": "WhatsApp"}


def _mm(mm: float) -> int:
    return round(mm * DPI / 25.4)


def _fuente(tam: int, negrita: bool = False):
    try:
        return ImageFont.truetype(str(_FUENTE_BOLD if negrita else _FUENTE_SEMI), tam)
    except OSError:  # pragma: no cover
        return ImageFont.load_default(size=tam)


def _get(obj, clave: str, defecto=None):
    if isinstance(obj, dict):
        return obj.get(clave, defecto)
    return getattr(obj, clave, defecto)


def _partir(draw, texto: str, fuente, ancho: int) -> list[str]:
    palabras, lineas, actual = str(texto).split(), [], ""
    for palabra in palabras:
        prueba = f"{actual} {palabra}".strip()
        if draw.textlength(prueba, font=fuente) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas or [""]


def _fecha_legible(venta) -> str:
    """"13/11/2026 · 3:45 p.m." en hora de Bogotá (R2); si no hay hora UTC,
    la fecha local tal cual."""
    from core.timeutil import BOGOTA, parse_iso_utc

    try:
        local = parse_iso_utc(str(_get(venta, "fecha_hora_utc", ""))).astimezone(BOGOTA)
    except Exception:
        return str(_get(venta, "fecha_local", ""))
    hora = local.strftime("%I:%M %p").lstrip("0").replace("AM", "a.m.").replace("PM", "p.m.")
    return f"{local.strftime('%d/%m/%Y')} · {hora}"


def generar_imagen_recibo(
    venta,
    *,
    nombre_negocio: str = "Ola Tata · Bolsos & Accesorios",
    mensaje: str = "¡Gracias por tu compra!",
    vendedor: str | None = None,
    ancho_papel_mm: int = 80,
) -> Image.Image:
    if ancho_papel_mm not in ANCHOS_PAPEL_MM:
        raise ValueError("El ancho de la tirilla debe ser 80 o 58 mm.")
    ancho = _mm(ancho_papel_mm)
    util = _mm(ANCHOS_PAPEL_MM[ancho_papel_mm])
    x0 = (ancho - util) // 2
    escala = util / _mm(72)

    f_normal = _fuente(int(24 * escala))
    f_peque = _fuente(int(20 * escala))
    f_bold = _fuente(int(26 * escala), negrita=True)
    f_titulo = _fuente(int(32 * escala), negrita=True)
    f_total = _fuente(int(44 * escala), negrita=True)

    # Lienzo alto de sobra; se recorta al final.
    lienzo = Image.new("L", (ancho, 6000), 255)
    d = ImageDraw.Draw(lienzo)
    y = _mm(2)

    def centrado(texto, fuente):
        nonlocal y
        for linea in _partir(d, texto, fuente, util):
            d.text((x0 + (util - d.textlength(linea, font=fuente)) / 2, y), linea, font=fuente, fill=0)
            y += int(sum(fuente.getmetrics()) * 1.05)

    def par(izq, der, fuente):
        nonlocal y
        ancho_der = d.textlength(der, font=fuente)
        lineas = _partir(d, izq, fuente, util - int(ancho_der) - _mm(3))
        for i, linea in enumerate(lineas):
            d.text((x0, y), linea, font=fuente, fill=0)
            if i == len(lineas) - 1:
                d.text((x0 + util - ancho_der, y), der, font=fuente, fill=0)
            y += int(sum(fuente.getmetrics()) * 1.05)

    def linea_punteada():
        nonlocal y
        y += _mm(1)
        for x in range(x0, x0 + util, 12):
            d.line([(x, y), (x + 6, y)], fill=0, width=2)
        y += _mm(2)

    if _LOGO.exists():
        logo = Image.open(_LOGO).convert("L")
        lado = _mm(22)
        logo = logo.resize((lado, lado))
        lienzo.paste(logo, ((ancho - lado) // 2, y))
        y += lado + _mm(1.5)

    centrado(nombre_negocio, f_titulo)
    y += _mm(1)
    centrado(f"Venta {_get(venta, 'numero', '')}", f_bold)
    centrado(_fecha_legible(venta), f_normal)
    canal = _CANALES.get(str(_get(venta, "canal", "")), "")
    if canal:
        centrado(f"Canal: {canal}", f_peque)
    if vendedor:
        centrado(f"Atendió: {vendedor}", f_peque)
    linea_punteada()

    for item in _get(venta, "items", []) or []:
        cantidad = int(_get(item, "cantidad", 1))
        nombre = str(_get(item, "nombre_snapshot", ""))
        total_linea = int(_get(item, "total_linea", 0))
        par(f"{cantidad} x {nombre}", format_cop(total_linea), f_normal)
        if cantidad > 1:
            par(f"   {format_cop(int(_get(item, 'precio_unitario', 0)))} c/u", "", f_peque)
    linea_punteada()

    par("Subtotal", format_cop(int(_get(venta, "subtotal", 0))), f_normal)
    descuento = int(_get(venta, "descuento_total", 0) or 0)
    if descuento:
        par("Descuento", f"-{format_cop(descuento)}", f_normal)
    envio = int(_get(venta, "envio_cobrado", 0) or 0)
    if envio:
        par("Envío", format_cop(envio), f_normal)
    y += _mm(1)
    par("TOTAL", format_cop(int(_get(venta, "total", 0))), f_total)
    y += _mm(1)
    for pago in _get(venta, "pagos", []) or []:
        metodo = _METODOS.get(str(_get(pago, "metodo", "")), str(_get(pago, "metodo", "")))
        par(metodo, format_cop(int(_get(pago, "monto", 0))), f_peque)

    cliente = _get(venta, "cliente_nombre", "")
    if cliente and str(cliente).strip() and str(cliente).lower() != "nan":
        y += _mm(1)
        par("Cliente", str(cliente), f_peque)
    linea_punteada()
    if mensaje:
        centrado(mensaje, f_peque)
    y += _mm(8)  # margen para el cortador

    recortado = lienzo.crop((0, 0, ancho, y))
    return recortado.point(lambda v: 0 if v < 160 else 255, mode="1")


def generar_pdf_recibo(venta, **kwargs) -> bytes:
    """PDF de una página: 80 (o 58) mm de ancho × lo que mida el recibo."""
    imagen = generar_imagen_recibo(venta, **kwargs)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PDF", resolution=float(DPI))
    return buffer.getvalue()
