from core.config import DEFAULT_DB_PATH, safe_secret


def test_safe_secret_usa_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("OLATATA_TEST_KEY", "valor-de-entorno")
    assert safe_secret("OLATATA_TEST_KEY") == "valor-de-entorno"


def test_safe_secret_devuelve_default_si_no_existe(monkeypatch):
    monkeypatch.delenv("OLATATA_TEST_KEY_INEXISTENTE", raising=False)
    assert safe_secret("OLATATA_TEST_KEY_INEXISTENTE", default="por-defecto") == "por-defecto"


def test_safe_secret_sin_default_devuelve_none(monkeypatch):
    monkeypatch.delenv("OLATATA_TEST_KEY_INEXISTENTE", raising=False)
    assert safe_secret("OLATATA_TEST_KEY_INEXISTENTE") is None


def test_default_db_path_es_el_esperado():
    assert DEFAULT_DB_PATH == "OLATATA_DB.xlsx"
