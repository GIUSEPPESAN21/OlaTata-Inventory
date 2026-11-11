"""Verifica que nadie haya cambiado por error los colores de marca del
tema (§9) en `.streamlit/config.toml`. No se puede probar contraste de
forma 100% automática, pero sí que los valores hexadecimales exactos
del encargo sigan presentes."""
from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"

# Tokens de marca fijos (§9 del encargo) — NO cambiar sin acuerdo del
# coordinador, son los que ya pasaron la verificación de contraste.
PRIMARIO = "#C2185B"
FONDO = "#FDEFF0"
BARRA_LATERAL = "#FCE8EC"
TINTA = "#2B1B22"


def _leer_config() -> dict:
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def test_config_toml_existe():
    assert CONFIG_PATH.exists()


def test_tema_es_claro_fijo():
    config = _leer_config()
    assert config["theme"]["base"] == "light"


def test_colores_de_marca_no_cambiaron():
    config = _leer_config()
    tema = config["theme"]
    assert tema["primaryColor"] == PRIMARIO
    assert tema["backgroundColor"] == FONDO
    assert tema["secondaryBackgroundColor"] == BARRA_LATERAL
    assert tema["textColor"] == TINTA


def test_proteccion_xsrf_activa():
    config = _leer_config()
    assert config["server"]["enableXsrfProtection"] is True


def test_no_se_envian_estadisticas_de_uso():
    config = _leer_config()
    assert config["browser"]["gatherUsageStats"] is False
