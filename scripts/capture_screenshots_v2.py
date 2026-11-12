"""Captura de pantallas del rediseño visual v2 (A5 — SHELL/TEMA/AJUSTES).

Herramienta de verificación visual, no un script de negocio: automatiza
con Playwright el recorrido login -> vender (vacío/carrito/recibo) ->
inventario (con filtros/vacío) -> análisis (Hoy/Semana/Mes) -> ajustes,
en la resolución que se le pida, y guarda cada pantalla en
`docs/capturas/v2/`.

Requisitos antes de correrlo:
1. Generar datos demo: `DEMO=1 .venv/Scripts/python.exe scripts/seed_demo.py --dias 90 --ventas-por-dia 40`
2. Levantar la app apuntando a ese libro, por ejemplo:
   ```
   $env:DEMO = "1"; $env:OLATATA_DB_PATH = "demo/OLATATA_DEMO.xlsx"
   .venv/Scripts/python.exe -m streamlit run app.py --server.headless true --server.port 8524 --server.fileWatcherType none
   ```
   (`--server.fileWatcherType none` + un puerto fresco por cada ronda de
   cambios evita servir código viejo cacheado en `sys.modules`).
3. Correr este script con la resolución deseada:
   `.venv/Scripts/python.exe scripts/capture_screenshots_v2.py desktop --url http://localhost:8524`

Usuarios demo esperados (creados por `scripts/seed_demo.py`):
`admin.demo` / `Demo-12345`.

Nota: el producto usado para probar "Cobrar" debe tener stock real en el
libro demo (se consume 1 unidad cada vez que este script corre con
éxito) — ajustar `PRODUCTO_CON_STOCK`/`MONTO_PRODUCTO` si se agota.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "capturas" / "v2"

VIEWPORTS = {
    "desktop": {"width": 1366, "height": 768},
    "fullhd": {"width": 1920, "height": 1080},
    "mobile": {"width": 390, "height": 844},
}

PRODUCTO_CON_STOCK = "P-000014"
MONTO_PRODUCTO = "55000"


def shot(page, name: str) -> None:
    """Captura TODO el contenido de la pantalla. `[data-testid="stMain"]`
    es su PROPIO contenedor con scroll interno (el `<body>` del documento
    no crece) — un `page.screenshot(full_page=True)` normal solo captura
    lo que ya está visible en ese scroll interno en ese momento, nunca el
    resto. Se agranda temporalmente el viewport a la altura real de
    `stMain.scrollHeight` (sin scroll interno pendiente) para que una
    captura de viewport normal muestre la pantalla completa, y se
    restaura el tamaño original después."""
    original_vp = page.viewport_size
    try:
        page.evaluate("document.querySelector('[data-testid=\"stMain\"]').scrollTop = 0")
        scroll_height = page.evaluate("document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
        sidebar_height = page.evaluate(
            "(() => { const s = document.querySelector('[data-testid=\"stSidebar\"]'); return s ? s.scrollHeight : 0; })()"
        )
        target_height = max(scroll_height, sidebar_height, original_vp["height"]) + 40
        if target_height > original_vp["height"]:
            page.set_viewport_size({"width": original_vp["width"], "height": target_height})
            page.wait_for_timeout(200)
        page.screenshot(path=str(OUT_DIR / name))
    finally:
        if page.viewport_size != original_vp:
            page.set_viewport_size(original_vp)
    print("saved", name)


def goto_nav(page, label: str) -> None:
    """Hace clic en un ítem del menú lateral. A <=576px Streamlit colapsa
    la barra lateral en un cajón superpuesto (control ">>"/"<<", stable
    testid `stSidebarCollapsedControl`) — si el botón del menú no está
    visible todavía, primero se abre ese cajón."""
    boton = page.get_by_role("button", name=label, exact=True)
    if boton.count() == 0 or not boton.first.is_visible():
        control = page.get_by_test_id("stSidebarCollapsedControl")
        if control.count() > 0:
            control.first.click()
            page.wait_for_timeout(500)
    # `is_visible()` solo mira CSS (display/visibility), no intersección
    # real con el viewport -- en el cajón superpuesto de móvil el botón
    # puede ser "visible" para Playwright y aun así quedar fuera del
    # rectángulo visible, con lo que `.click()` normal (e incluso
    # `force=True`) se niega a "apuntar" a un punto inexistente en
    # pantalla. Se dispara el click nativo en el DOM por texto siempre
    # que la intersección con el viewport sea nula; si es real, se deja
    # el click normal de Playwright (dispara los mismos eventos que una
    # persona real, mejor cuando funciona).
    caja = boton.first.bounding_box()
    vp = page.viewport_size
    interseca = bool(
        caja and vp and caja["x"] < vp["width"] and caja["y"] < vp["height"] and caja["x"] + caja["width"] > 0 and caja["y"] + caja["height"] > 0
    )
    if interseca:
        boton.click()
    else:
        page.evaluate(
            """(texto) => {
                const botones = Array.from(document.querySelectorAll('[data-testid="stSidebar"] button'));
                const boton = botones.find((b) => b.textContent.includes(texto));
                if (boton) boton.click();
            }""",
            label,
        )
    page.wait_for_timeout(1200)


def run_for_viewport(p, base_url: str, tag: str, vp: dict) -> None:
    browser = p.chromium.launch()
    context = browser.new_context(viewport=vp)
    page = context.new_page()
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    # 1) Login
    page.goto(base_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    shot(page, f"01_login_{tag}.png")

    # 2) Error de formulario (credenciales inválidas)
    page.get_by_label("Usuario").fill("usuario_invalido")
    page.get_by_label("Contraseña").fill("clave_mala")
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_timeout(1000)
    shot(page, f"02_login_error_{tag}.png")

    # 3) Login real
    page.get_by_label("Usuario").fill("")
    page.get_by_label("Usuario").fill("admin.demo")
    page.get_by_label("Contraseña").fill("")
    page.get_by_label("Contraseña").fill("Demo-12345")
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_timeout(2000)
    shot(page, f"03_vender_{tag}.png")

    # 4) Vender: agregar producto al carrito
    try:
        page.get_by_label("Buscar por nombre, código o escanear").fill(PRODUCTO_CON_STOCK)
        page.get_by_role("button", name="Agregar al carrito").click()
        page.wait_for_timeout(1200)
        shot(page, f"04_vender_carrito_{tag}.png")
    except Exception as exc:  # pragma: no cover - herramienta de verificación, no de negocio
        print("vender carrito error", exc)

    # 5) Cobrar. NOTA (hallazgo de A5 para A2, ver informe final): el
    # botón "Completar con el total restante" no actualiza el
    # number_input visible porque el widget ya tiene su propio valor en
    # session_state desde el primer render — se llena el campo "Monto"
    # directamente en vez de depender de ese botón.
    try:
        page.get_by_label("Monto").fill(MONTO_PRODUCTO)
        page.get_by_label("Monto").press("Tab")
        page.wait_for_timeout(1200)
        boton_cobrar = page.get_by_role("button", name="Cobrar")
        boton_cobrar.wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            "document.querySelector('button[data-testid=\"stBaseButton-primary\"]') && "
            "!document.querySelector('button[data-testid=\"stBaseButton-primary\"]').disabled",
            timeout=10000,
        )
        boton_cobrar.click()
        page.wait_for_timeout(1500)
        shot(page, f"05_recibo_{tag}.png")
        page.get_by_role("button", name="Nueva venta").click()
        page.wait_for_timeout(1000)
    except Exception as exc:  # pragma: no cover
        print("cobrar error (revisar stock de", PRODUCTO_CON_STOCK, "):", exc)

    # 6) Inventario (con filtros y estado vacío)
    try:
        goto_nav(page, "Inventario")
        shot(page, f"06_inventario_{tag}.png")
        campo_busqueda = page.get_by_label("Buscar por nombre o código de barras")
        campo_busqueda.fill("zzzz_no_existe")
        campo_busqueda.press("Enter")
        page.wait_for_timeout(1000)
        shot(page, f"07_inventario_vacio_{tag}.png")
    except Exception as exc:  # pragma: no cover
        print("inventario error", exc)

    # 7) Análisis: Hoy / Semana / Mes
    try:
        goto_nav(page, "Análisis")
        shot(page, f"08_analisis_hoy_{tag}.png")
        page.get_by_role("tab", name="Semana").click()
        page.wait_for_timeout(1200)
        shot(page, f"09_analisis_semana_{tag}.png")
        page.get_by_role("tab", name="Mes", exact=True).click()
        page.wait_for_timeout(1200)
        shot(page, f"10_analisis_mes_{tag}.png")
    except Exception as exc:  # pragma: no cover
        print("analisis error", exc)

    # 8) Ajustes
    try:
        goto_nav(page, "Ajustes")
        shot(page, f"11_ajustes_{tag}.png")
    except Exception as exc:  # pragma: no cover
        print("ajustes error", exc)

    try:
        fonts_ready = page.evaluate("document.fonts.ready.then(() => document.fonts.size)")
        print(f"[{tag}] fuentes cargadas:", fonts_ready)
    except Exception as exc:  # pragma: no cover
        print("fonts check error", exc)

    print(f"[{tag}] errores de consola:", console_errors)

    context.close()
    browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("viewport", choices=sorted(VIEWPORTS), help="Resolución a capturar")
    parser.add_argument("--url", default="http://localhost:8501", help="URL base de la app ya corriendo")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        run_for_viewport(p, args.url, args.viewport, VIEWPORTS[args.viewport])


if __name__ == "__main__":
    main()
