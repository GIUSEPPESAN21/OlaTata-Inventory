import pytest

from core.excel_safe import TextoInvalidoError, csv_safe, excel_safe


def test_texto_igual_formula_pasa_intacto():
    assert excel_safe("=1+1") == "=1+1"
    assert excel_safe("@SUM(1)") == "@SUM(1)"


def test_none_se_vuelve_cadena_vacia():
    assert excel_safe(None) == ""


def test_quita_caracteres_de_control_pero_conserva_salto_de_linea_y_tab():
    sucio = "Hola\x00Mundo\nLinea2\tTab\x07"
    limpio = excel_safe(sucio)
    assert "\x00" not in limpio
    assert "\x07" not in limpio
    assert "\n" in limpio
    assert "\t" in limpio


def test_recorta_espacios_externos():
    assert excel_safe("   hola   ") == "hola"


def test_respeta_limite_de_largo():
    excel_safe("a" * 10, max_length=10)
    with pytest.raises(TextoInvalidoError):
        excel_safe("a" * 11, max_length=10)


def test_convierte_no_string_a_string():
    assert excel_safe(123) == "123"


def test_csv_safe_antepone_apostrofo_a_formulas():
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("+1") == "'+1"
    assert csv_safe("-1") == "'-1"
    assert csv_safe("@SUM(1)") == "'@SUM(1)"


def test_csv_safe_no_modifica_texto_normal():
    assert csv_safe("Bolso negro") == "Bolso negro"


def test_csv_safe_none_se_vuelve_cadena_vacia():
    assert csv_safe(None) == ""
