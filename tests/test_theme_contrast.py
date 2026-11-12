"""Contraste WCAG de cada par texto/fondo real usado en la paleta de
marca (C1 del encargo de A5). Calcula la relación de contraste exacta
(fórmula WCAG 2.x de luminancia relativa) para cada combinación que la
UI usa de verdad (botones, texto de cuerpo, chips, alertas) y falla si
baja de 4.5:1 — o de 3:1 quando el par se usa solo para texto grande
(>=24 px, p.ej. títulos Playfair) o iconos, igual que exige el WCAG AA
para "large text".
"""
from __future__ import annotations

from core.ui import TOKENS

COLOR = TOKENS["color"]


def _canal_lineal(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminancia_relativa(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    r_lin, g_lin, b_lin = _canal_lineal(r), _canal_lineal(g), _canal_lineal(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def razon_de_contraste(color_a: str, color_b: str) -> float:
    l1 = _luminancia_relativa(color_a)
    l2 = _luminancia_relativa(color_b)
    claro, oscuro = max(l1, l2), min(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)


# (texto, fondo, descripción, razón mínima exigida)
# 4.5:1 -> texto normal (cuerpo, formularios, botones).
# 3.0:1 -> texto grande (>=24px, p.ej. títulos Playfair/KPIs) o iconos.
PARES_TEXTO_NORMAL = [
    ("#FFFFFF", COLOR["primario"], "texto blanco sobre botón primario"),
    (COLOR["tinta"], COLOR["fondo"], "tinta sobre fondo de página"),
    (COLOR["tinta"], COLOR["superficie"], "tinta sobre superficie (tarjetas)"),
    (COLOR["tinta"], COLOR["sidebar"], "tinta sobre barra lateral"),
    (COLOR["texto_secundario"], COLOR["fondo"], "texto secundario sobre fondo"),
    (COLOR["texto_secundario"], COLOR["superficie"], "texto secundario sobre superficie"),
    (COLOR["texto_secundario"], COLOR["sidebar"], "texto secundario sobre barra lateral"),
    (COLOR["dorado_texto"], COLOR["fondo"], "texto dorado sobre fondo"),
    (COLOR["dorado_texto"], COLOR["superficie"], "texto dorado sobre superficie"),
    (COLOR["exito"], COLOR["superficie"], "texto de éxito sobre superficie"),
    (COLOR["error"], COLOR["superficie"], "texto de error sobre superficie"),
    (COLOR["alerta_texto"], COLOR["alerta_fondo"], "texto de alerta sobre fondo de alerta"),
    (COLOR["primario"], COLOR["superficie"], "enlaces/primario sobre superficie"),
    # Rediseño visual (A5): pares nuevos introducidos por el sistema de
    # tarjetas/KPI/total del carrito (assets/theme.css). Nota: el chip
    # "info" y la etiqueta TOTAL usaban antes `dorado_texto` sobre
    # `rosa_veta` (4.09:1, no pasa 4.5:1 en texto chico) — se corrigió a
    # `texto_secundario` (4.93:1), por eso aquí solo se fija el par bueno.
    (COLOR["tinta"], COLOR["rosa_veta"], "tinta sobre rosa veta (total del carrito)"),
    (COLOR["texto_secundario"], COLOR["rosa_veta"], "texto secundario sobre rosa veta (etiqueta TOTAL, chip info)"),
    # Fondos literales de los chips/KPI de estado (no son TOKENS con
    # nombre porque son un matiz MÁS claro que fondo/sidebar, pensado
    # solo para la píldora): #E3F3EA daba 4.40:1 con `exito` (<4.5:1,
    # texto chico) -- se aclaró a #EEF8F2 (4.66:1).
    (COLOR["exito"], "#EEF8F2", "texto de éxito sobre fondo de chip/kpi de éxito"),
    (COLOR["error"], "#FBE9E7", "texto de error sobre fondo de chip/kpi de error"),
]

PARES_TEXTO_GRANDE_O_ICONO = [
    (COLOR["primario"], COLOR["fondo"], "título Playfair (color primario) sobre fondo"),
    (COLOR["primario"], COLOR["rosa_veta"], "icono de marca sobre rosa veta (círculo de kpi_card/hero)"),
]


def test_pares_texto_normal_cumplen_4_5_a_1():
    fallidos = []
    for fg, bg, descripcion in PARES_TEXTO_NORMAL:
        razon = razon_de_contraste(fg, bg)
        if razon < 4.5:
            fallidos.append(f"{descripcion}: {razon:.2f}:1 (< 4.5:1)")
    assert not fallidos, "\n".join(fallidos)


def test_pares_texto_grande_o_icono_cumplen_3_a_1():
    fallidos = []
    for fg, bg, descripcion in PARES_TEXTO_GRANDE_O_ICONO:
        razon = razon_de_contraste(fg, bg)
        if razon < 3.0:
            fallidos.append(f"{descripcion}: {razon:.2f}:1 (< 3.0:1)")
    assert not fallidos, "\n".join(fallidos)


def test_rosa_de_marca_y_rosa_veta_nunca_se_usan_con_texto_blanco_encima():
    """§9/C1: `#FC7DA9` y `#F8C0D8` son acentos/rellenos, NUNCA fondo de
    texto blanco (su contraste con blanco es demasiado bajo). Esta
    prueba documenta el motivo con el número real, no solo la regla."""
    razon_rosa_marca = razon_de_contraste("#FFFFFF", COLOR["rosa_marca"])
    razon_rosa_veta = razon_de_contraste("#FFFFFF", COLOR["rosa_veta"])
    assert razon_rosa_marca < 4.5
    assert razon_rosa_veta < 4.5


def test_texto_blanco_sobre_primario_coincide_con_la_cifra_documentada():
    """CLAUDE.md §8 documenta 5.87:1 para texto blanco sobre `#C2185B`."""
    razon = razon_de_contraste("#FFFFFF", COLOR["primario"])
    assert abs(razon - 5.87) < 0.05
