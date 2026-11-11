"""Dinero en pesos colombianos (COP): siempre enteros, nunca float.

CONTRATO CONGELADO — ver docs/CONTRATOS.md. R1 del encargo: ningún peso
se guarda ni se calcula con `float`. Los porcentajes usan `Decimal` y
solo se redondean al mostrarlos.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "DineroInvalidoError",
    "parse_pesos",
    "format_cop",
    "round_half_up_pesos",
    "format_percent",
]


class DineroInvalidoError(ValueError):
    """Un valor de dinero no es un entero de pesos válido."""


def parse_pesos(value: object) -> int:
    """Convierte una entrada (usuario, Excel, formulario) a pesos enteros.

    Acepta ``int``, ``float`` sin parte decimal, o ``str`` con formato
    "$ 1.250.000" / "1250000" / "1.250.000". RECHAZA cualquier valor con
    decimales distintos de cero (R1: "rechaza decimales").
    """
    if isinstance(value, bool):
        raise DineroInvalidoError(f"Valor booleano no es dinero válido: {value!r}")

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not value.is_integer():
            raise DineroInvalidoError(
                f"El valor {value} tiene decimales; los pesos colombianos son "
                "siempre enteros."
            )
        return int(value)

    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise DineroInvalidoError(
                f"El valor {value} tiene decimales; los pesos colombianos son "
                "siempre enteros."
            )
        return int(value)

    if isinstance(value, str):
        texto = value.strip()
        if texto == "":
            raise DineroInvalidoError("El valor de dinero está vacío.")
        texto = texto.replace("$", "").replace(" ", "")
        negativo = texto.startswith("-")
        if negativo:
            texto = texto[1:]
        # Punto como separador de miles (formato colombiano). Si hay una
        # coma, se interpreta como separador decimal: solo se acepta si
        # los decimales son "00" (equivalentes a cero).
        if "," in texto:
            entero, _, decimales = texto.partition(",")
            if decimales.strip("0") != "":
                raise DineroInvalidoError(
                    f"El valor '{value}' tiene decimales; los pesos colombianos "
                    "son siempre enteros."
                )
            texto = entero
        texto = texto.replace(".", "")
        if not texto.isdigit():
            raise DineroInvalidoError(f"'{value}' no es un valor de dinero válido.")
        monto = int(texto)
        return -monto if negativo else monto

    raise DineroInvalidoError(f"Tipo no soportado para dinero: {type(value)!r}")


def format_cop(value: int) -> str:
    """Formatea pesos enteros como "$ 1.250.000" (punto de miles, sin decimales)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise DineroInvalidoError(f"format_cop requiere un entero, recibió {value!r}")
    signo = "-" if value < 0 else ""
    miles = f"{abs(value):,}".replace(",", ".")
    return f"{signo}$ {miles}"


def round_half_up_pesos(value: Decimal | int | float | str) -> int:
    """Redondea a peso entero, mitad hacia arriba (para costo promedio, R5)."""
    if isinstance(value, float):
        value = Decimal(str(value))
    elif not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def format_percent(numerador: int, denominador: int, decimales: int = 1) -> str:
    """Porcentaje con `Decimal`, redondeo mitad arriba; "—" si denominador es 0."""
    if denominador == 0:
        return "—"
    pct = (Decimal(numerador) / Decimal(denominador)) * Decimal(100)
    cuanto = Decimal(1).scaleb(-decimales)
    pct = pct.quantize(cuanto, rounding=ROUND_HALF_UP)
    return f"{pct}%"
