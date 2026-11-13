"""Etiquetas de precio para la impresora térmica de etiquetas del negocio.

Hardware real (fotos del local, 2026-11-13):
- Impresora de etiquetas DigitalPOS (térmica, 203 dpi típico) con rollo de
  **3 etiquetas por fila** (estilo 32 × 25 mm; se confirma con regla el día
  de la prueba y se ajusta en el perfil, sin tocar código).
- Lector de códigos DigitalPOS USB que funciona como TECLADO: "escribe" el
  código y envía Enter.

Lo que se imprimía antes (etiqueta vieja): "OLA TATA", nombre repetido,
fecha y un texto que se salía del borde ("6/00" cortado), barras muy bajas
con el número "1367" encima de ellas, precio con coma ("$ 98,000"). Diseño
nuevo, por prioridad: 1) ARTÍCULO (negrita, hasta 2 líneas), 2) CÓDIGO DE
BARRAS (alto, centrado, con zona de silencio y número legible debajo),
3) PRECIO (lo más grande de la etiqueta, formato COP "$ 98.000").

Cómo se imprime:
- PDF con el tamaño FÍSICO exacto: cada página = una fila del rollo
  (p.ej. 3 × 32 mm + separaciones = ~104 × 25 mm). Se imprime desde el
  navegador con el driver de la impresora configurado con ese tamaño de
  papel, escala 100 % / "tamaño real".
- TSPL (respaldo): las mismas imágenes como `BITMAP` en lenguaje TSPL,
  para enviar el archivo directo a la impresora sin driver (ver
  docs/IMPRESORAS.md). Es idéntico píxel a píxel al PDF.

Las barras se dibujan a mano a partir de la codificación Code128 de
`python-barcode` con un número ENTERO de puntos por módulo: escalar una
imagen de barras (lo que hacía `labels_ot`) emborrona los bordes y el
lector falla. Módulo puro (sin Streamlit ni `storage`).
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import barcode as _barcode_lib
from PIL import Image, ImageDraw, ImageFont

from core.money import format_cop
from core.permissions import requerir

__all__ = [
    "PerfilEtiqueta",
    "PERFILES_PREDEFINIDOS",
    "PERFIL_POR_DEFECTO",
    "ItemEtiqueta",
    "codigo_interno",
    "id_desde_codigo_interno",
    "codigo_para_producto",
    "normalizar_lectura_escaner",
    "perfil_desde_json",
    "perfil_a_json",
    "componer_etiqueta",
    "componer_filas",
    "generar_pdf",
    "generar_pdf_calibracion",
    "generar_tspl",
    "modulo_barras_px",
    "CLAVE_CONFIG_PERFIL",
    "cargar_perfil",
    "guardar_perfil",
]

CLAVE_CONFIG_PERFIL = "etiquetas_perfil"

_RAIZ = Path(__file__).resolve().parent.parent
_FUENTE_BOLD = _RAIZ / "assets" / "fonts" / "inter-bold.otf"
_FUENTE_SEMI = _RAIZ / "assets" / "fonts" / "inter-semibold.otf"

PREFIJO_CODIGO_INTERNO = "20"


# ------------------------------------------------------------------ perfil
@dataclass(frozen=True)
class PerfilEtiqueta:
    """Geometría del rollo de etiquetas, en milímetros."""

    nombre: str = "3 por fila · 32 × 25 mm"
    ancho_mm: float = 32.0
    alto_mm: float = 25.0
    columnas: int = 3
    separacion_mm: float = 3.0  # espacio horizontal entre etiquetas de una fila
    margen_izq_mm: float = 1.0  # desde el borde del papel hasta la 1.ª etiqueta
    gap_vertical_mm: float = 2.0  # espacio entre filas (solo para TSPL)
    dpi: int = 203

    def __post_init__(self) -> None:
        if not (10 <= self.ancho_mm <= 120 and 10 <= self.alto_mm <= 120):
            raise ValueError("El tamaño de la etiqueta debe estar entre 10 y 120 mm.")
        if not (1 <= self.columnas <= 4):
            raise ValueError("Las columnas por fila deben estar entre 1 y 4.")
        if self.separacion_mm < 0 or self.margen_izq_mm < 0 or self.gap_vertical_mm < 0:
            raise ValueError("Las separaciones no pueden ser negativas.")
        if self.dpi not in (203, 300):
            raise ValueError("La resolución debe ser 203 o 300 dpi.")

    @property
    def puntos_por_mm(self) -> float:
        return self.dpi / 25.4

    def mm_a_px(self, mm: float) -> int:
        return round(mm * self.puntos_por_mm)

    @property
    def ancho_fila_mm(self) -> float:
        return self.margen_izq_mm + self.columnas * self.ancho_mm + (self.columnas - 1) * self.separacion_mm

    @property
    def descripcion_papel(self) -> str:
        return f"{self.ancho_fila_mm:g} × {self.alto_mm:g} mm"


PERFILES_PREDEFINIDOS: dict[str, PerfilEtiqueta] = {
    p.nombre: p
    for p in (
        PerfilEtiqueta(),
        PerfilEtiqueta(nombre="3 por fila · 30 × 20 mm", ancho_mm=30, alto_mm=20, separacion_mm=3),
        PerfilEtiqueta(nombre="2 por fila · 50 × 25 mm", ancho_mm=50, alto_mm=25, columnas=2, separacion_mm=3),
        PerfilEtiqueta(nombre="1 por fila · 50 × 30 mm", ancho_mm=50, alto_mm=30, columnas=1, separacion_mm=0),
        PerfilEtiqueta(nombre="1 por fila · 40 × 30 mm", ancho_mm=40, alto_mm=30, columnas=1, separacion_mm=0),
    )
}
PERFIL_POR_DEFECTO = PerfilEtiqueta()


def perfil_a_json(perfil: PerfilEtiqueta) -> str:
    return json.dumps(asdict(perfil), ensure_ascii=False)


def perfil_desde_json(texto: str | None) -> PerfilEtiqueta:
    """Lee el perfil guardado en CONFIG (`etiquetas_perfil`). Ante cualquier
    valor dañado devuelve el perfil por defecto (nunca truena)."""
    if not texto:
        return PERFIL_POR_DEFECTO
    try:
        datos = json.loads(texto)
        campos = set(PerfilEtiqueta.__dataclass_fields__)
        return PerfilEtiqueta(**{k: v for k, v in datos.items() if k in campos})
    except (ValueError, TypeError):
        return PERFIL_POR_DEFECTO


# ------------------------------------------------------------------ códigos
def codigo_interno(producto_id: str) -> str:
    """"OT-000123" -> "20000123": código NUMÉRICO de 8 dígitos para la
    etiqueta cuando el producto no trae código de barras propio. Numérico
    porque (1) Code128 lo comprime (barras más anchas = lectura más
    segura en una etiqueta de 32 mm) y (2) un lector USB tipo teclado no
    depende de la distribución del teclado para dígitos (el "-" de
    "OT-000123" sale como "'" con teclado latinoamericano)."""
    digitos = re.sub(r"\D", "", str(producto_id or ""))
    if not digitos:
        raise ValueError(f"El producto '{producto_id}' no tiene un id numérico.")
    numero = int(digitos)
    if numero >= 1_000_000:
        raise ValueError(f"Id fuera de rango para código interno: {producto_id}")
    return f"{PREFIJO_CODIGO_INTERNO}{numero:06d}"


def id_desde_codigo_interno(texto: str) -> str | None:
    """"20000123" -> "OT-000123"; `None` si no es un código interno."""
    texto = (texto or "").strip()
    if re.fullmatch(rf"{PREFIJO_CODIGO_INTERNO}\d{{6}}", texto):
        return f"OT-{texto[len(PREFIJO_CODIGO_INTERNO):]}"
    return None


def codigo_para_producto(producto_id: str, codigo_barras: str | None) -> str:
    """El código propio del producto si lo tiene (p.ej. el EAN del
    proveedor); si no, el código interno numérico."""
    propio = "" if codigo_barras is None else str(codigo_barras).strip()
    if propio and propio.lower() not in ("nan", "none") and propio.isascii():
        return propio
    return codigo_interno(producto_id)


def normalizar_lectura_escaner(texto: str) -> str:
    """Limpia lo que "teclea" el lector: espacios, caracteres de control y
    el apóstrofo que produce el guion con teclado latinoamericano."""
    limpio = "".join(ch for ch in (texto or "") if ch.isprintable()).strip()
    return limpio.replace("'", "-").replace("´", "-")


# ------------------------------------------------------------------ dibujo
@dataclass(frozen=True)
class ItemEtiqueta:
    nombre: str
    codigo: str
    precio: int | None = None


@lru_cache(maxsize=64)
def _fuente(tamano_px: int, negrita: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    ruta = _FUENTE_BOLD if negrita else _FUENTE_SEMI
    try:
        return ImageFont.truetype(str(ruta), tamano_px)
    except OSError:  # pragma: no cover - solo si faltara el archivo de fuente
        return ImageFont.load_default(size=tamano_px)


def _modulos_code128(codigo: str) -> str:
    clase = _barcode_lib.get_barcode_class("code128")
    return clase(codigo).build()[0]


def modulo_barras_px(codigo: str, ancho_disponible_px: int) -> int:
    """Puntos por módulo (barra más delgada) que caben, con 10 módulos de
    zona de silencio a cada lado si se puede (mínimo 4)."""
    modulos = len(_modulos_code128(codigo))
    for zona in (10, 7, 4):
        modulo = ancho_disponible_px // (modulos + 2 * zona)
        if modulo >= 2:
            return min(modulo, 4)
    return max(1, ancho_disponible_px // (modulos + 8))


def _envolver(draw: ImageDraw.ImageDraw, texto: str, fuente, ancho: int, max_lineas: int) -> list[str]:
    palabras = texto.split()
    lineas: list[str] = []
    actual = ""
    for palabra in palabras:
        prueba = f"{actual} {palabra}".strip()
        if draw.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
            continue
        if actual:
            lineas.append(actual)
        actual = palabra
        if len(lineas) == max_lineas:
            break
    if actual and len(lineas) < max_lineas:
        lineas.append(actual)
    usadas = " ".join(lineas).split()
    if len(usadas) < len(palabras) and lineas:  # no cupo todo: recorta con "…"
        ultima = lineas[-1]
        while ultima and draw.textlength(ultima + "…", font=fuente) > ancho:
            ultima = ultima[:-1]
        lineas[-1] = ultima.rstrip() + "…"
    # una palabra sola más ancha que la etiqueta
    return [_recortar(draw, linea, fuente, ancho) for linea in lineas]


def _recortar(draw, texto: str, fuente, ancho: int) -> str:
    if draw.textlength(texto, font=fuente) <= ancho:
        return texto
    while texto and draw.textlength(texto + "…", font=fuente) > ancho:
        texto = texto[:-1]
    return texto + "…"


def _alto_texto(fuente) -> int:
    ascenso, descenso = fuente.getmetrics()
    return ascenso + descenso


def _dibujar_barras(draw: ImageDraw.ImageDraw, codigo: str, x0: int, y0: int, ancho: int, alto: int) -> None:
    patron = _modulos_code128(codigo)
    modulo = modulo_barras_px(codigo, ancho)
    ancho_barras = len(patron) * modulo
    x = x0 + max(0, (ancho - ancho_barras) // 2)
    for bit in patron:
        if bit == "1":
            draw.rectangle([x, y0, x + modulo - 1, y0 + alto - 1], fill=0)
        x += modulo


def componer_etiqueta(item: ItemEtiqueta, perfil: PerfilEtiqueta = PERFIL_POR_DEFECTO) -> Image.Image:
    """Una etiqueta en blanco y negro puro (modo "1") al tamaño físico del
    perfil. Prioridad visual: artículo, código de barras, precio."""
    if not str(item.codigo or "").strip():
        raise ValueError(f"El producto '{item.nombre}' no tiene código para la etiqueta.")
    for max_lineas in (2, 1):  # si las barras quedan muy bajas, el nombre cede a 1 línea
        img = _dibujar_etiqueta(item, perfil, max_lineas)
        if img is not None:
            return img
    return _dibujar_etiqueta(item, perfil, 1, forzar=True)


def _dibujar_etiqueta(item: ItemEtiqueta, perfil: PerfilEtiqueta, max_lineas: int, forzar: bool = False):
    ancho = perfil.mm_a_px(perfil.ancho_mm)
    alto = perfil.mm_a_px(perfil.alto_mm)
    margen = perfil.mm_a_px(1.2)
    util_w = ancho - 2 * margen
    util_h = alto - 2 * margen
    escala = alto / 200  # diseño base: 25 mm a 203 dpi = 200 px de alto

    img = Image.new("L", (ancho, alto), 255)
    draw = ImageDraw.Draw(img)

    # 3) PRECIO abajo: lo más grande que quepa a lo ancho.
    alto_precio = 0
    if item.precio is not None:
        texto_precio = format_cop(int(item.precio))
        tam = int(46 * escala)
        fuente_precio = _fuente(tam)
        while tam > 14 and draw.textlength(texto_precio, font=fuente_precio) > util_w:
            tam -= 2
            fuente_precio = _fuente(tam)
        alto_precio = fuente_precio.getbbox(texto_precio)[3]
        x_precio = margen + (util_w - draw.textlength(texto_precio, font=fuente_precio)) / 2
        draw.text((x_precio, margen + util_h - alto_precio), texto_precio, font=fuente_precio, fill=0)

    # 1) ARTÍCULO arriba, en mayúscula y negrita.
    fuente_nombre = _fuente(max(12, int(22 * escala)))
    nombre = " ".join(str(item.nombre or "").upper().split())
    lineas = _envolver(draw, nombre, fuente_nombre, util_w, max_lineas) if nombre else []
    interlinea = int(_alto_texto(fuente_nombre) * 0.92)
    y = margen
    for linea in lineas:
        draw.text((margen + (util_w - draw.textlength(linea, font=fuente_nombre)) / 2, y), linea, font=fuente_nombre, fill=0)
        y += interlinea

    # 2) CÓDIGO DE BARRAS en el medio + número legible debajo.
    fuente_codigo = _fuente(max(10, int(15 * escala)), negrita=False)
    espacio = max(2, int(4 * escala))
    y_barras = y + espacio
    alto_barras = (margen + util_h - alto_precio - espacio) - _alto_texto(fuente_codigo) - y_barras
    if alto_barras < perfil.mm_a_px(5) and not forzar:
        return None
    alto_barras = max(alto_barras, perfil.mm_a_px(3))
    _dibujar_barras(draw, item.codigo, margen, y_barras, util_w, alto_barras)
    numero = str(item.codigo)
    draw.text(
        (margen + (util_w - draw.textlength(numero, font=fuente_codigo)) / 2, y_barras + alto_barras + 1),
        numero,
        font=fuente_codigo,
        fill=0,
    )
    # Blanco y negro puro: la térmica no imprime grises (los "tramaría").
    return img.point(lambda v: 0 if v < 150 else 255, mode="1")


def componer_filas(items: list[ItemEtiqueta], perfil: PerfilEtiqueta = PERFIL_POR_DEFECTO) -> list[Image.Image]:
    """Agrupa las etiquetas en filas del rollo (una imagen por fila)."""
    if not items:
        raise ValueError("No hay etiquetas para imprimir.")
    ancho_fila = perfil.mm_a_px(perfil.ancho_fila_mm)
    alto = perfil.mm_a_px(perfil.alto_mm)
    filas: list[Image.Image] = []
    for inicio in range(0, len(items), perfil.columnas):
        fila = Image.new("1", (ancho_fila, alto), 1)
        for col, item in enumerate(items[inicio : inicio + perfil.columnas]):
            x = perfil.mm_a_px(perfil.margen_izq_mm + col * (perfil.ancho_mm + perfil.separacion_mm))
            fila.paste(componer_etiqueta(item, perfil), (x, 0))
        filas.append(fila)
    return filas


def _pdf(imagenes: list[Image.Image], dpi: int) -> bytes:
    buffer = io.BytesIO()
    imagenes[0].save(buffer, format="PDF", save_all=True, append_images=imagenes[1:], resolution=float(dpi))
    return buffer.getvalue()


def generar_pdf(items: list[ItemEtiqueta], perfil: PerfilEtiqueta = PERFIL_POR_DEFECTO) -> bytes:
    """PDF con una página por fila, al tamaño físico exacto del rollo."""
    return _pdf(componer_filas(items, perfil), perfil.dpi)


def generar_pdf_calibracion(perfil: PerfilEtiqueta = PERFIL_POR_DEFECTO) -> bytes:
    """Una fila de prueba: borde de cada etiqueta, su número y medidas, y
    un código de prueba. Sirve para comprobar el día de la instalación que
    el tamaño de papel y el centrado del driver coinciden con el rollo."""
    fila = componer_filas(
        [ItemEtiqueta(nombre=f"Prueba {i + 1}", codigo=codigo_interno(str(i + 1)), precio=98000) for i in range(perfil.columnas)],
        perfil,
    )[0].convert("L")
    draw = ImageDraw.Draw(fila)
    fuente = _fuente(max(10, perfil.mm_a_px(1.6)), negrita=False)
    for col in range(perfil.columnas):
        x = perfil.mm_a_px(perfil.margen_izq_mm + col * (perfil.ancho_mm + perfil.separacion_mm))
        w = perfil.mm_a_px(perfil.ancho_mm)
        h = perfil.mm_a_px(perfil.alto_mm)
        draw.rectangle([x, 0, x + w - 1, h - 1], outline=0, width=2)
        draw.text((x + 4, h - _alto_texto(fuente) - 2), f"{perfil.ancho_mm:g}×{perfil.alto_mm:g}", font=fuente, fill=0)
    return _pdf([fila.point(lambda v: 0 if v < 150 else 255, mode="1")], perfil.dpi)


def generar_tspl(
    items: list[ItemEtiqueta], perfil: PerfilEtiqueta = PERFIL_POR_DEFECTO, *, invertir: bool = False
) -> bytes:
    """Mismas filas en lenguaje TSPL (impresoras de etiquetas tipo TSC,
    como la DigitalPOS) usando `BITMAP`: no depende de las fuentes de la
    impresora (tildes, "ñ" y "$" salen igual que en el PDF). En TSPL un
    bit 0 = punto negro; `invertir=True` por si un modelo lo toma al revés."""
    salida = bytearray()
    for fila in componer_filas(items, perfil):
        ancho_bytes = (fila.width + 7) // 8
        relleno = Image.new("1", (ancho_bytes * 8, fila.height), 1)
        relleno.paste(fila, (0, 0))
        datos = relleno.tobytes()  # modo "1": 1 = blanco, 0 = negro
        if invertir:
            datos = bytes(b ^ 0xFF for b in datos)
        salida += (
            f"SIZE {perfil.ancho_fila_mm:g} mm,{perfil.alto_mm:g} mm\r\n"
            f"GAP {perfil.gap_vertical_mm:g} mm,0 mm\r\n"
            "DIRECTION 1\r\nREFERENCE 0,0\r\nCLS\r\n"
            f"BITMAP 0,0,{ancho_bytes},{fila.height},0,"
        ).encode("ascii")
        salida += datos
        salida += b"\r\nPRINT 1,1\r\n"
    return bytes(salida)


def con_perfil(perfil: PerfilEtiqueta, **cambios) -> PerfilEtiqueta:
    """Copia del perfil con cambios (valida de nuevo)."""
    return replace(perfil, **cambios)


# ---------------------------------------------------------- persistencia
def cargar_perfil(storage) -> PerfilEtiqueta:
    """Perfil guardado en CONFIG (o el de 3 por fila 32 × 25 mm)."""
    return perfil_desde_json(storage.get_config("etiquetas_perfil"))


def guardar_perfil(tx, rol: str | None, perfil: PerfilEtiqueta) -> None:
    """Dentro de `storage.transaction()`. Solo quien puede imprimir
    etiquetas (admin) cambia el perfil del rollo (revalidado aquí, §10)."""
    requerir(rol, "etiquetas")
    tx.set_config("etiquetas_perfil", perfil_a_json(perfil))
