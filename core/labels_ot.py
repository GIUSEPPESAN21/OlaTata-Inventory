"""LEGADO: reemplazado por `core/etiquetas.py` (tamaño físico del rollo,
varias por fila, barras nítidas). Se conserva por compatibilidad.

Etiquetas con código de barras en PDF (§6: "etiquetas con código de
barras en PDF").

Propiedad exclusiva de A1 (INVENTARIO). No es un contrato congelado — ver
docs/CONTRATOS.md para la lista de módulos que SÍ lo son.

Usa `python-barcode` (Code128, ya está en requirements.txt) para el código
de barras y SOLO `Pillow` para componer la etiqueta y el PDF multipágina
(`Image.save(..., "PDF", save_all=True)`) — no se agregó `reportlab` ni
`fpdf2` (no están permitidos por el encargo; ver informe final si esto
resultara insuficiente para un caso real).

Este módulo es una utilidad pura (no toca `storage`): el control de
permisos ("etiquetas", solo admin) lo hace quien lo llama — en este
proyecto, `views/inventario.py` — antes de invocar cualquier función de
aquí, igual que exige §10.
"""
from __future__ import annotations

import io

import barcode as _barcode_lib
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont

from core.money import format_cop

__all__ = [
    "LABEL_WIDTH_PX",
    "LABEL_HEIGHT_PX",
    "generar_imagen_codigo_barras",
    "generar_etiqueta",
    "generar_pdf_etiquetas",
]

LABEL_WIDTH_PX = 400
LABEL_HEIGHT_PX = 260
_MARGIN = 16
_ALTO_BARRA_MAX = 130


def _cargar_fuente(size: int) -> ImageFont.ImageFont:
    """Fuente TrueType si está disponible en el sistema; si no, la fuente
    por defecto de Pillow (nunca falla la generación de la etiqueta)."""
    for nombre in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generar_imagen_codigo_barras(codigo_barras: str) -> Image.Image:
    """Genera la imagen (Code128) del código de barras, en memoria."""
    codigo_barras = (codigo_barras or "").strip()
    if not codigo_barras:
        raise ValueError("El código de barras no puede estar vacío.")
    clase = _barcode_lib.get_barcode_class("code128")
    writer = ImageWriter()
    instancia = clase(codigo_barras, writer=writer)
    buffer = io.BytesIO()
    instancia.write(buffer, options={"write_text": False, "quiet_zone": 2})
    buffer.seek(0)
    return Image.open(buffer).convert("L")


def generar_etiqueta(
    *,
    nombre: str,
    codigo_barras: str,
    precio: int | None = None,
    ancho_px: int = LABEL_WIDTH_PX,
    alto_px: int = LABEL_HEIGHT_PX,
) -> Image.Image:
    """Compone una etiqueta: nombre del producto, código de barras legible
    como imagen y, si se da, el precio formateado ("$ 1.250.000", R1)."""
    etiqueta = Image.new("RGB", (ancho_px, alto_px), color="white")
    draw = ImageDraw.Draw(etiqueta)

    nombre_mostrado = (nombre or "").strip()
    fuente_nombre = _cargar_fuente(18)
    # Recorta el nombre si no cabe en el ancho de la etiqueta.
    while nombre_mostrado and draw.textlength(nombre_mostrado, font=fuente_nombre) > ancho_px - 2 * _MARGIN:
        nombre_mostrado = nombre_mostrado[:-1]
    draw.text((_MARGIN, _MARGIN), nombre_mostrado, fill="black", font=fuente_nombre)

    barra = generar_imagen_codigo_barras(codigo_barras)
    ancho_barra_destino = ancho_px - 2 * _MARGIN
    alto_barra_destino = min(_ALTO_BARRA_MAX, int(ancho_barra_destino * barra.height / barra.width))
    barra = barra.resize((ancho_barra_destino, max(1, alto_barra_destino)))

    y_barra = _MARGIN + 34
    etiqueta.paste(barra.convert("RGB"), (_MARGIN, y_barra))

    y_texto = y_barra + barra.height + 10
    fuente_codigo = _cargar_fuente(16)
    draw.text((_MARGIN, y_texto), codigo_barras, fill="black", font=fuente_codigo)

    if precio is not None:
        fuente_precio = _cargar_fuente(20)
        draw.text((_MARGIN, y_texto + 26), format_cop(int(precio)), fill="black", font=fuente_precio)

    return etiqueta


def generar_pdf_etiquetas(productos: list[dict]) -> bytes:
    """PDF multipágina (una etiqueta por producto) usando SOLO Pillow.

    `productos`: lista de dicts con, al menos, `nombre` y `codigo_barras`;
    `precio` es opcional. Lanza `ValueError` si la lista está vacía o si
    algún producto no trae código de barras.
    """
    if not productos:
        raise ValueError("No hay productos seleccionados para generar etiquetas.")

    imagenes = []
    for producto in productos:
        codigo_barras = (producto.get("codigo_barras") or "").strip()
        if not codigo_barras:
            nombre = producto.get("nombre", "(sin nombre)")
            raise ValueError(f"El producto '{nombre}' no tiene código de barras asignado.")
        imagenes.append(
            generar_etiqueta(
                nombre=producto.get("nombre", ""),
                codigo_barras=codigo_barras,
                precio=producto.get("precio"),
            )
        )

    buffer = io.BytesIO()
    imagenes[0].save(buffer, format="PDF", save_all=True, append_images=imagenes[1:])
    return buffer.getvalue()
