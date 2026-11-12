"""Genera los assets de marca de Ola Tata a partir del logo oficial.

Propiedad de A5 (SHELL/TEMA/AJUSTES). Script reproducible: no se editan
las imágenes a mano. Entrada real verificada (ver `docs/CONTRATOS.md` y
el informe de A5): `C:\\Users\\LENOVO\\Downloads\\olatata-logo.jpg`,
JPEG de 690x690 px, círculo rosado con aros dorados sobre fondo
cuadrado gris claro (NO transparente) — por eso hace falta recorte
circular con máscara.

Salidas, todas en `assets/brand/`:
- olatata-logo-original.png   -> copia intacta en PNG (sin recortar).
- olatata-logo.png (512x512)  -> recorte circular, fondo transparente,
  antialiasing, 3 px hacia adentro del borde para quitar el halo gris.
- olatata-logo-256.png / -128.png / -64.png -> derivados del circular.
- favicon.ico (16/32/48), favicon-32.png, apple-touch-icon.png (180x180
  sobre fondo #FDEFF0).
- olatata-logo-mono.png -> blanco y negro con umbral, para recibo
  térmico/impresión.

Uso:
    .venv/Scripts/python.exe scripts/build_logo_assets.py
    .venv/Scripts/python.exe scripts/build_logo_assets.py --origen "ruta.jpg"
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ORIGEN = Path(r"C:\Users\LENOVO\Downloads\olatata-logo.jpg")
SALIDA_DIR = REPO_ROOT / "assets" / "brand"
FONDO_CLARO = (253, 239, 240)  # #FDEFF0, para el apple-touch-icon

TAMANO_CIRCULAR_BASE = 512
INSET_PX = 3  # recorta hacia adentro del borde para quitar el halo gris
DERIVADOS = (256, 128, 64)
TAMANOS_FAVICON_ICO = (48, 32, 16)
TAMANO_APPLE_TOUCH = 180
UMBRAL_MONO = 150


def _mascara_circular_antialiased(tamano: int, inset_px: int) -> Image.Image:
    """Máscara circular suave (antialiasing por supersampleo 4x)."""
    escala = 4
    grande = tamano * escala
    inset_grande = inset_px * escala
    mascara_grande = Image.new("L", (grande, grande), 0)
    draw = ImageDraw.Draw(mascara_grande)
    draw.ellipse(
        [inset_grande, inset_grande, grande - inset_grande, grande - inset_grande],
        fill=255,
    )
    mascara = mascara_grande.resize((tamano, tamano), Image.LANCZOS)
    return mascara.filter(ImageFilter.GaussianBlur(radius=0.6))


def recorte_circular(origen: Image.Image, tamano: int, inset_px: int) -> Image.Image:
    cuadrado = origen.convert("RGB").resize((tamano, tamano), Image.LANCZOS)
    mascara = _mascara_circular_antialiased(tamano, inset_px)
    resultado = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    resultado.paste(cuadrado, (0, 0))
    resultado.putalpha(mascara)
    return resultado


def verificar_esquinas_transparentes(imagen: Image.Image) -> None:
    ancho, alto = imagen.size
    esquinas = [(0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)]
    for x, y in esquinas:
        alpha = imagen.getpixel((x, y))[3]
        if alpha != 0:
            raise AssertionError(f"Esquina ({x},{y}) no es transparente: alpha={alpha}")


def generar_favicon_ico(circular_512: Image.Image, destino: Path) -> None:
    imagenes = [circular_512.resize((t, t), Image.LANCZOS) for t in TAMANOS_FAVICON_ICO]
    imagenes[0].save(
        destino,
        format="ICO",
        sizes=[(t, t) for t in TAMANOS_FAVICON_ICO],
        append_images=imagenes[1:],
    )


def generar_apple_touch_icon(circular_512: Image.Image, destino: Path) -> None:
    lienzo = Image.new("RGB", (TAMANO_APPLE_TOUCH, TAMANO_APPLE_TOUCH), FONDO_CLARO)
    logo = circular_512.resize((TAMANO_APPLE_TOUCH, TAMANO_APPLE_TOUCH), Image.LANCZOS)
    lienzo.paste(logo, (0, 0), logo)
    lienzo.save(destino, format="PNG")


def generar_mono(circular_512: Image.Image, destino: Path) -> None:
    """Versión blanco y negro con umbral, para recibo térmico. Se
    compone primero sobre blanco (el recibo imprime sobre papel blanco)
    y luego se umbraliza a 1 bit real de contraste (negro/blanco)."""
    sobre_blanco = Image.new("RGB", circular_512.size, (255, 255, 255))
    sobre_blanco.paste(circular_512, (0, 0), circular_512)
    gris = sobre_blanco.convert("L")
    mono = gris.point(lambda p: 255 if p > UMBRAL_MONO else 0, mode="L")
    mono.save(destino, format="PNG")


def sha256_de(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origen", type=Path, default=DEFAULT_ORIGEN)
    parser.add_argument("--salida", type=Path, default=SALIDA_DIR)
    args = parser.parse_args()

    if not args.origen.exists():
        raise SystemExit(f"No se encontró el logo de origen: {args.origen}")

    args.salida.mkdir(parents=True, exist_ok=True)

    origen_img = Image.open(args.origen)
    print(f"Origen: {args.origen} -> {origen_img.size} {origen_img.mode}")

    # 1) Copia intacta en PNG (sin recortar, sin recomprimir con pérdida).
    original_png = args.salida / "olatata-logo-original.png"
    origen_img.convert("RGB").save(original_png, format="PNG")
    print(f"Original: {original_png} hash={sha256_de(original_png)[:12]}…")

    # 2) Recorte circular base 512x512, fondo transparente.
    circular_512 = recorte_circular(origen_img, TAMANO_CIRCULAR_BASE, INSET_PX)
    verificar_esquinas_transparentes(circular_512)
    circular_512.save(args.salida / "olatata-logo.png", format="PNG")
    print("Circular 512x512: alpha=0 en las 4 esquinas, verificado.")

    # 3) Derivados.
    for tamano in DERIVADOS:
        derivado = circular_512.resize((tamano, tamano), Image.LANCZOS)
        verificar_esquinas_transparentes(derivado)
        derivado.save(args.salida / f"olatata-logo-{tamano}.png", format="PNG")
        print(f"Derivado {tamano}x{tamano} generado.")

    # 4) Favicon .ico multi-resolución + PNG 32.
    generar_favicon_ico(circular_512, args.salida / "favicon.ico")
    circular_512.resize((32, 32), Image.LANCZOS).save(
        args.salida / "favicon-32.png", format="PNG"
    )
    print("favicon.ico (16/32/48) y favicon-32.png generados.")

    # 5) Apple touch icon sobre fondo claro de marca.
    generar_apple_touch_icon(circular_512, args.salida / "apple-touch-icon.png")
    print("apple-touch-icon.png (180x180, fondo #FDEFF0) generado.")

    # 6) Versión monocromática para recibo térmico/impresión.
    generar_mono(circular_512, args.salida / "olatata-logo-mono.png")
    print("olatata-logo-mono.png (blanco y negro, umbral) generado.")

    # 7) Muestreo de color para reconciliar la paleta (solo informativo;
    # los tokens de core/ui.py quedan fijos por CLAUDE.md §8).
    rgb = origen_img.convert("RGB")
    ancho, alto = rgb.size
    cx, cy = ancho // 2, alto // 2
    muestra_rosa = rgb.getpixel((cx, cy + alto // 3))
    muestra_dorado = rgb.getpixel((int(ancho * 0.18), int(alto * 0.5)))
    print(f"Muestra rosa de fondo (aprox): RGB{muestra_rosa}")
    print(f"Muestra dorado de aro (aprox): RGB{muestra_dorado}")

    print("Listo. Revisa assets/brand/README.md para el detalle de cada archivo.")


if __name__ == "__main__":
    main()
