"""Verificación visual automatizada con Playwright (A5 — SHELL/TEMA/AJUSTES).

Complementa `tests/test_theme_contrast.py` (contraste WCAG, estático) y
`tests/test_regresion_referencias.py` (sin `.st-emotion-cache-*`,
estático): esto levanta la app REAL contra un libro demo diminuto y
revisa, con un navegador de verdad:
- las fuentes de marca (Inter/Playfair Display/Great Vibes/Material
  Symbols) terminan cargadas (`document.fonts`), no solo declaradas;
- cero errores de consola del navegador al cargar login + la primera
  pantalla tras ingresar;
- sin desborde horizontal a 390px (viewport móvil, D-responsive): el
  `<body>` nunca debe ser más ancho que la ventana.

Lento comparado con el resto de la suite (levanta un servidor real) —
se mantiene en un módulo aparte y con un dataset mínimo (unos pocos
días de ventas) para que siga siendo razonable dentro de `pytest -q`.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

playwright_sync_api = pytest.importorskip("playwright.sync_api")


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servidor_demo(tmp_path_factory):
    """Levanta `streamlit run app.py` en modo demo contra un libro
    diminuto y 100% ficticio (reutiliza `scripts.seed_demo`, la misma
    compuerta `DEMO=1` que usa la app en producción). Se cierra al
    terminar el módulo."""
    from core.storage import Storage
    from scripts.seed_demo import poblar_demo

    ruta = tmp_path_factory.mktemp("visual_playwright") / "OLATATA_DEMO.xlsx"
    storage = Storage(local_path=ruta, sync_enabled=False)
    poblar_demo(storage, dias=5, ventas_por_dia=5, fecha_inicio=date(2025, 9, 1))

    puerto = _puerto_libre()
    env = os.environ.copy()
    env["DEMO"] = "1"
    env["OLATATA_DB_PATH"] = str(ruta)
    proceso = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(puerto),
            "--server.fileWatcherType",
            "none",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://localhost:{puerto}"
    listo = False
    for _ in range(60):
        try:
            urllib.request.urlopen(base_url, timeout=1)
            listo = True
            break
        except Exception:
            time.sleep(1)
    if not listo:
        proceso.terminate()
        pytest.fail("El servidor de Streamlit no respondió a tiempo para las pruebas visuales.")

    try:
        yield base_url
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()


def _login(page, usuario: str = "admin.demo", password: str = "Demo-12345") -> None:
    page.get_by_label("Usuario").fill(usuario)
    page.get_by_label("Contraseña").fill(password)
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_timeout(1500)


def test_fuentes_de_marca_terminan_cargadas(servidor_demo):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(servidor_demo, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        # "Material Symbols Outlined" (icono_md/chip_estado/kpi_card/
        # estado_vacio) solo se solicita en pantallas que de verdad pintan
        # un icono propio -- el login no usa ninguna. Se entra a Vender
        # (encabezado_pagina(..., icono=...)) para que las 4 fuentes de
        # marca estén realmente en uso antes de revisar `document.fonts`.
        _login(page)
        page.wait_for_timeout(1000)
        # `document.fonts.ready` solo espera las fuentes YA solicitadas por
        # el CSS aplicado en ese instante -- con un arranque en frío del
        # servidor (primera carga real) pueden solicitarse unos
        # milisegundos después de "networkidle". Se reintenta un par de
        # veces en vez de un único `wait_for_timeout` fijo.
        familias_cargadas: list[str] = []
        requeridas_local = {"Inter", "Playfair Display", "Great Vibes", "Material Symbols Outlined"}
        for _ in range(10):
            page.wait_for_timeout(500)
            page.evaluate("document.fonts.ready")
            familias_cargadas = page.evaluate(
                "() => Array.from(document.fonts).filter(f => f.status === 'loaded').map(f => f.family)"
            )
            if all(any(req in f for f in familias_cargadas) for req in requeridas_local):
                break
        browser.close()

    requeridas = {"Inter", "Playfair Display", "Great Vibes", "Material Symbols Outlined"}
    faltantes = {f for f in requeridas if not any(f in familia for familia in familias_cargadas)}
    assert not faltantes, f"Fuentes declaradas pero no cargadas: {faltantes} (cargadas: {familias_cargadas})"


def test_sin_errores_de_consola_en_login_y_primera_pantalla(servidor_demo):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        errores = []
        page.on("console", lambda msg: errores.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errores.append(str(exc)))

        page.goto(servidor_demo, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        _login(page)
        page.wait_for_timeout(1500)
        browser.close()

    assert not errores, f"Errores de consola del navegador: {errores}"


def test_sin_desborde_horizontal_a_390px(servidor_demo):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(servidor_demo, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        _login(page)
        page.wait_for_timeout(1500)

        ancho_viewport = page.evaluate("window.innerWidth")
        ancho_documento = page.evaluate("document.documentElement.scrollWidth")
        browser.close()

    assert ancho_documento <= ancho_viewport + 1, (
        f"Desborde horizontal a 390px: documento={ancho_documento}px > viewport={ancho_viewport}px"
    )
