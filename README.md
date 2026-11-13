# Ola Tata · Inventario y Ventas

Aplicación de inventario, punto de venta y análisis para
**Ola Tata – Bolsos y Accesorios** (Buga / Tuluá, Colombia;
Instagram [@olatata_1](https://instagram.com/olatata_1)). Vende por
tienda, Instagram y WhatsApp, cobra con datáfono, transferencia,
efectivo y Sistecrédito, y hace envíos nacionales.

Desarrollado por **SAVA**.

## Qué hace

- **Vender** (`views/vender.py`): venta rápida con búsqueda por nombre,
  código de barras o escáner USB, carrito en `st.session_state`,
  descuentos, pago dividido entre varios métodos, recibo de texto y
  botón para enviarlo por WhatsApp.
- **Ventas** (`views/ventas.py`): historial por rango de fechas (el
  vendedor solo ve las propias; el admin ve todas), devolución/cambio y
  anulación de ventas (solo admin, con motivo obligatorio).
- **Inventario** (`views/inventario.py`): productos, stock, proveedores,
  importación masiva y etiquetas.
- **Análisis** (`views/analisis.py`): KPIs e indicadores de ventas e
  inventario.
- **Ajustes** (`views/ajustes.py`, solo admin): datos del negocio,
  usuarios, estado de sincronización con GitHub, respaldo descargable,
  verificación de integridad y **cierre de mes**.

Toda la lógica de negocio vive en `core/` (sin Streamlit, 100%
testeable); `app.py` solo hace enrutado y manejo de sesión; cada
pantalla vive en `views/` y expone `render(ctx)`.

## Stack

Python 3.12 (CI) / 3.11 (desarrollo local) · Streamlit 1.66 · pandas ·
openpyxl · plotly · bcrypt · python-barcode · Pillow · requests.

## Estructura

```
app.py            # enrutado y sesión únicamente (login, primer arranque, menú)
views/            # una pantalla por módulo: vender, ventas, inventario, analisis, ajustes, login, primer_arranque
core/             # lógica de negocio pura, sin Streamlit, 100% testeable
  schema.py       # las 13 hojas del libro y sus columnas
  storage.py      # Storage: transacciones atómicas + sync a GitHub + Archive
  fastxlsx.py     # escritura rápida de .xlsx (ver docs/CONTRATOS.md)
  money.py        # dinero siempre en int COP
  timeutil.py     # cortes de día/semana/mes en America/Bogota
  permissions.py  # capacidades por rol (admin/vendedor), revalidadas en core/
  auth.py         # login, hash de contraseñas, sesiones
  sales.py / returns.py / receipts.py   # venta, devolución/anulación, recibo
  inventory.py / costing.py / importer.py / labels_ot.py  # inventario
  analytics.py / cash_close.py / excel_report.py          # análisis y cuadre de caja
  monthly_close.py / archive.py         # cierre mensual (ver docs/ARQUITECTURA.md)
tests/            # pytest (core/ en >=85% de cobertura, bloqueante en CI)
scripts/          # seed_demo.py (datos ficticios) y smoke_e2e.py (prueba end-to-end)
assets/           # logo y estáticos
.streamlit/       # tema (config.toml) y secretos (secrets.toml, nunca se sube)
docs/             # CONTRATOS.md (API congelada), ARQUITECTURA.md, QA_CHECKLIST.md
```

## Correr en local

Requiere Python 3.11 o 3.12.

```bash
# 1. Crear y activar un entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell / cmd)
# source .venv/bin/activate      # macOS / Linux

# 2. Instalar dependencias de desarrollo (incluye las de producción)
pip install -r requirements-dev.txt

# 3. Correr la app
streamlit run app.py
```

Al abrir la app por primera vez (sin usuarios creados), aparece el
asistente de **primer arranque**: crea el usuario administrador con una
contraseña temporal y obliga a cambiarla antes de continuar.

Sin `.streamlit/secrets.toml`, la app funciona igual en modo 100%
local: `core.config.safe_secret` nunca truena si no hay secretos, y
`Storage` arranca con `sync_enabled=False` (todo se guarda en
`OLATATA_DB.xlsx` local, sin publicar a GitHub). Para probar la
sincronización real, copia `.streamlit/secrets.toml.example` a
`.streamlit/secrets.toml` y completa los 3 valores (ver `DEPLOY.md`).

## Probar

```bash
# Pruebas rápidas (sin medir cobertura)
pytest -q

# Pruebas + cobertura de core/ (igual que en CI, bloqueante en >=85%)
pytest tests/ --cov=core --cov-report=term-missing --cov-fail-under=85

# Lint
ruff check .

# Smoke end-to-end (90 días simulados, datos ficticios, semilla fija)
python scripts/smoke_e2e.py
```

Estos son exactamente los pasos que corre `.github/workflows/ci.yml` en
cada push/PR a `main` (Python 3.11 y 3.12 en paralelo). La cobertura de
`views/` y `app.py` se reporta de forma informativa, sin bloquear el
build.

Para explorar la app con datos de ejemplo (100% ficticios, nunca datos
reales de clientes). Requiere `DEMO=1`; sin esa variable el script
termina con error y no escribe nada, y nunca puede publicar a GitHub ni
sobrescribir `OLATATA_DB.xlsx` (ver `docs/CONTRATOS.md`):

```bash
DEMO=1 python scripts/seed_demo.py --dias 90 --ventas-por-dia 40
# escribe en demo/OLATATA_DEMO.xlsx (en .gitignore)
```

## Repos relacionados

Este proyecto vive en 3 repositorios separados, a propósito: el código
nunca comparte repositorio con los datos reales del negocio.

- `OlaTata-Inventory` — este repositorio. Todo el código de la app
  (`app.py`, `views/`, `core/`, `tests/`, `scripts/`). No contiene datos
  de clientes ni secretos: `*.xlsx`, `demo/` y `.streamlit/secrets.toml`
  están en `.gitignore` (ver `DEPLOY.md` para el detalle de por qué esto
  permite, si se quisiera, que este repo sea público).
- `OlaTata-Database` — base viva (mes en curso), privado, sin código.
  Solo contiene `OLATATA_DB.xlsx`, publicado por `core/storage.py` al
  cerrar cada `transaction()`. Su historial de commits de git es, en la
  práctica, el historial de versiones del libro vivo (ver "Restaurar una
  versión anterior" en `DEPLOY.md`).
- `OlaTata-Archive` — archivo inmutable de meses cerrados, privado, sin
  código. Un archivo `cierres/AAAA-MM.xlsx` por cada mes cerrado (ver
  `core/monthly_close.py` y `docs/ARQUITECTURA.md`), más
  `cierres/INDEX.json` con el resumen de todos los cierres publicados.

## Documentación

- `DEPLOY.md` — despliegue en Streamlit Community Cloud y configuración
  del token de GitHub.
- `MANUAL_USUARIO.md` — guía corta por rol (Dueño/a, Vendedor/a), con
  capturas de pantalla reales.
- `docs/SEGURIDAD.md` — controles de seguridad y lista de chequeo del dueño.
- `docs/IMPRESORAS.md` — impresora de etiquetas, tirilla de 80 mm y lector
  de códigos: cómo imprime la app y lista de chequeo para instalarlas.
- `docs/ARQUITECTURA.md` — esquema de datos, sincronización con GitHub,
  permisos, sistema de diseño y flujo del cierre mensual.
- `docs/CONTRATOS.md` — API congelada de los módulos base de `core/`.
- `CHANGELOG.md` — historial de hitos del proyecto, reconstruido a
  partir de `git log`.
