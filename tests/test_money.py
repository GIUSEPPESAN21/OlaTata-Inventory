from decimal import Decimal

import pytest

from core.money import (
    DineroInvalidoError,
    format_cop,
    format_percent,
    parse_pesos,
    round_half_up_pesos,
)


def test_parse_pesos_int():
    assert parse_pesos(1250000) == 1250000


def test_parse_pesos_float_entero():
    assert parse_pesos(1250000.0) == 1250000


def test_parse_pesos_float_con_decimales_rechazado():
    with pytest.raises(DineroInvalidoError):
        parse_pesos(1250000.50)


def test_parse_pesos_string_formateado():
    assert parse_pesos("$ 1.250.000") == 1250000
    assert parse_pesos("1.250.000") == 1250000
    assert parse_pesos("1250000") == 1250000


def test_parse_pesos_string_negativo():
    assert parse_pesos("-50.000") == -50000


def test_parse_pesos_string_con_coma_decimal_cero_se_acepta():
    assert parse_pesos("1.250.000,00") == 1250000


def test_parse_pesos_string_con_coma_decimal_distinta_de_cero_rechazado():
    with pytest.raises(DineroInvalidoError):
        parse_pesos("1.250.000,50")


def test_parse_pesos_bool_rechazado():
    with pytest.raises(DineroInvalidoError):
        parse_pesos(True)


def test_parse_pesos_vacio_rechazado():
    with pytest.raises(DineroInvalidoError):
        parse_pesos("")


def test_format_cop_miles():
    assert format_cop(1250000) == "$ 1.250.000"


def test_format_cop_cero():
    assert format_cop(0) == "$ 0"


def test_format_cop_negativo():
    assert format_cop(-50000) == "-$ 50.000"


def test_format_cop_rechaza_float():
    with pytest.raises(DineroInvalidoError):
        format_cop(1250000.0)  # type: ignore[arg-type]


def test_round_half_up_pesos():
    assert round_half_up_pesos(Decimal("100.5")) == 101
    assert round_half_up_pesos(Decimal("100.4")) == 100
    assert round_half_up_pesos(Decimal("-0.5")) == 0 or round_half_up_pesos(Decimal("-0.5")) == -1


def test_format_percent_normal():
    assert format_percent(25, 100) == "25.0%"


def test_format_percent_division_por_cero():
    assert format_percent(10, 0) == "—"


def test_format_percent_redondeo_mitad_arriba():
    # 1/3 = 33.333...%; con 1 decimal: 33.3%
    assert format_percent(1, 3) == "33.3%"
    # 0.125 -> 12.5% redondeado a 0 decimales -> 13% (mitad arriba)
    assert format_percent(125, 1000, decimales=0) == "13%"
