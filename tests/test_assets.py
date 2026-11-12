"""Pruebas de los assets de marca (A2/A4 del encargo de A5).

Verifica que `scripts/build_logo_assets.py` produjo todos los archivos
esperados, con los tamaños correctos, transparencia real en las
esquinas de cada PNG circular, y que el "original" sigue teniendo
exactamente los mismos píxeles que el logo de partida (congelado como
un hash de referencia, para no depender de que el archivo original de
`C:\\Users\\LENOVO\\Downloads\\...` exista en el entorno donde corre la
prueba, p.ej. en CI).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

BRAND_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand"

# Hash de referencia de los PÍXELES (no del archivo) de
# olatata-logo-original.png, calculado una sola vez cuando se generó a
# partir del logo oficial verificado por A5. Si este hash cambia es
# porque alguien reemplazó el logo de origen (requiere acuerdo del
# coordinador), no porque el script se haya ejecutado de nuevo con el
# mismo logo.
HASH_PIXELES_ORIGINAL = "c7daeb00775636c1e84acf7fb3cc85dd458e2360e0916fc60b5cf31a37c5fa60"

ARCHIVOS_Y_TAMANOS = {
    "olatata-logo-original.png": (690, 690),
    "olatata-logo.png": (512, 512),
    "olatata-logo-256.png": (256, 256),
    "olatata-logo-128.png": (128, 128),
    "olatata-logo-64.png": (64, 64),
    "favicon-32.png": (32, 32),
    "apple-touch-icon.png": (180, 180),
    "olatata-logo-mono.png": (512, 512),
}

ARCHIVOS_CIRCULARES_RGBA = [
    "olatata-logo.png",
    "olatata-logo-256.png",
    "olatata-logo-128.png",
    "olatata-logo-64.png",
    "favicon-32.png",
]


def test_todos_los_archivos_existen():
    faltantes = [nombre for nombre in ARCHIVOS_Y_TAMANOS if not (BRAND_DIR / nombre).exists()]
    assert not faltantes, f"Faltan assets de marca: {faltantes}"
    assert (BRAND_DIR / "favicon.ico").exists()
    assert (BRAND_DIR / "README.md").exists()


def test_tamanos_correctos():
    for nombre, tamano_esperado in ARCHIVOS_Y_TAMANOS.items():
        with Image.open(BRAND_DIR / nombre) as im:
            assert im.size == tamano_esperado, f"{nombre}: {im.size} != {tamano_esperado}"


def test_esquinas_transparentes_en_circulares():
    for nombre in ARCHIVOS_CIRCULARES_RGBA:
        with Image.open(BRAND_DIR / nombre) as im:
            rgba = im.convert("RGBA")
            ancho, alto = rgba.size
            esquinas = [(0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)]
            for x, y in esquinas:
                alpha = rgba.getpixel((x, y))[3]
                assert alpha == 0, f"{nombre} esquina ({x},{y}) no transparente: alpha={alpha}"


def test_favicon_ico_tiene_las_tres_resoluciones():
    with Image.open(BRAND_DIR / "favicon.ico") as im:
        tamanos = {size for size in im.info.get("sizes", [])}
        assert {(16, 16), (32, 32), (48, 48)} <= tamanos


def test_apple_touch_icon_sin_transparencia():
    with Image.open(BRAND_DIR / "apple-touch-icon.png") as im:
        assert im.mode in ("RGB", "RGBA")
        if im.mode == "RGBA":
            # si tiene canal alfa, debe estar completamente opaco
            alphas = im.getchannel("A").getextrema()
            assert alphas == (255, 255)


def test_mono_es_blanco_y_negro_puro():
    with Image.open(BRAND_DIR / "olatata-logo-mono.png") as im:
        gris = im.convert("L")
        valores = set(gris.getdata())
        # Umbralizado: solo deben existir (como mucho) los dos extremos.
        assert valores <= {0, 255}
        # Debe tener contenido real (no todo blanco ni todo negro).
        assert 0 in valores and 255 in valores


def test_original_coincide_en_pixeles_con_el_logo_de_partida():
    with Image.open(BRAND_DIR / "olatata-logo-original.png") as im:
        rgb = im.convert("RGB")
        hash_actual = hashlib.sha256(rgb.tobytes()).hexdigest()
    assert hash_actual == HASH_PIXELES_ORIGINAL, (
        "El contenido de píxeles de olatata-logo-original.png cambió "
        "respecto al logo oficial verificado. Si el logo oficial "
        "cambió a propósito, actualiza HASH_PIXELES_ORIGINAL de acuerdo "
        "con el coordinador."
    )
