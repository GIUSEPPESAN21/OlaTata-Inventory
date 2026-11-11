"""Saneamiento de texto libre (R11): nunca se pierde, nunca se interpreta
como fórmula, sin caracteres de control, con límite de largo.

La protección contra fórmulas al ESCRIBIR el .xlsx vive en
`core/storage.py` (fuerza `data_type="s"` en toda celda de texto). Este
módulo valida/limpia el texto ANTES de llegar a esa capa.
"""
from __future__ import annotations

import unicodedata

MAX_TEXT_LENGTH_DEFAULT = 2000

__all__ = ["TextoInvalidoError", "excel_safe", "csv_safe"]


class TextoInvalidoError(ValueError):
    """Un texto libre excede el largo permitido."""


def _es_caracter_de_control(ch: str) -> bool:
    if ch in ("\n", "\t"):
        return False
    return unicodedata.category(ch).startswith("C")


def excel_safe(value: object, *, max_length: int = MAX_TEXT_LENGTH_DEFAULT, field_name: str = "texto") -> str:
    """Limpia un texto libre: quita caracteres de control y valida el largo.

    Un valor como "=1+1" o "@SUM(1)" pasa intacto (el texto en sí NUNCA se
    modifica ni se pierde) — lo único que cambia es que los caracteres de
    control se eliminan y los espacios externos se recortan.
    """
    if value is None:
        return ""
    texto = value if isinstance(value, str) else str(value)
    texto = "".join(ch for ch in texto if not _es_caracter_de_control(ch))
    texto = texto.strip()
    if len(texto) > max_length:
        raise TextoInvalidoError(
            f"El campo '{field_name}' excede el largo máximo de {max_length} caracteres."
        )
    return texto


def csv_safe(value: object) -> str:
    """Antepone un apóstrofo si el texto podría interpretarse como fórmula
    al abrir un CSV exportado en Excel (OWASP CSV injection: =, +, -, @)."""
    texto = value if isinstance(value, str) else ("" if value is None else str(value))
    if texto.startswith(("=", "+", "-", "@")):
        return "'" + texto
    return texto
