# Changelog — Ola Tata · Inventario y Ventas

Reconstruido a partir de `git log --oneline` real de este repositorio
(46 commits en `main` al momento de escribir esto). Agrupado por hito
de desarrollo, no por fecha de calendario: el historial de este repo
quedó registrado con una única fecha de commit
(`2026-11-11`) para todos los commits, así que un listado "por día" no
aportaría información real — el orden real es el de `git log`, no el
de la fecha.

## Andamiaje inicial

- `8de3d5b` — Estructura inicial del repositorio: `.gitignore`,
  licencia y primer `README.md`.
- `b44a8ca` — Primera guía de despliegue (token de GitHub fine-grained)
  y plantilla de `secrets.toml`.
- `340a3b2` — Tema visual nativo con la paleta de marca en
  `.streamlit/config.toml`.
- `0ab172f` — `CLAUDE.md`: reglas no negociables del proyecto (dinero
  entero, hora de Bogotá, atomicidad, permisos revalidados en `core/`,
  texto seguro para Excel, stock nunca negativo, cierre mensual, paleta
  fija, cobertura de pruebas).

## M1 — Base congelada

- `75eaf25` — Congela `core/schema.py`, `core/money.py`,
  `core/timeutil.py`, `core/storage.py`, `core/permissions.py`,
  `core/auth.py`, `core/excel_safe.py`, el registro de vistas
  (`views/__init__.py`) y `docs/CONTRATOS.md`. CI local en verde con
  90% de cobertura en `core/`. A partir de aquí, estos módulos solo los
  modifica el agente coordinador.

## Integración de los módulos de dominio (A1–A6)

- **A1 — Inventario**: `534d180` costeo promedio ponderado y entradas
  de mercancía (R5); `94f11a7` CRUD de productos, conteo físico y
  verificación de integridad; `bc931d8` importación inicial con vista
  previa; `275bb0a` etiquetas con código de barras en PDF; `c4af68e` /
  `fe65040` vista real de Inventario integrada (solo admin).
- **A2 — Ventas**: `95d7eb8` venta/anulación/devolución con pruebas;
  `c8a6b21` integración: venta atómica e idempotente, pagos divididos,
  devoluciones y anulación.
- **A4 — Cierre mensual**: `a80710f` `core/monthly_close.py` y
  `core/archive.py`; `20cdbe9` integración: archivo, verificación e
  idempotencia del cierre.
- **A3 — Análisis**: `6d3086e` corrige el contrato de permisos (el
  admin también necesitaba `ver_analisis_basico`); `0383448` /
  `7599f4f` KPIs Hoy/Semana/Mes, cuadre de caja y exportación a Excel.
- **A5 — Shell/tema/ajustes**: `4ea4624` ajusta pruebas de vistas tras
  el fix de permisos; `0f679c5` / `7d007a8` `app.py` (enrutado y
  sesión), login, primer arranque, Ajustes y `core/ui.py`.
- **A6 — QA y datos**: `2002309` / `8c2b59e` datos de demostración,
  smoke end-to-end, presupuestos de rendimiento y regresión; `a804512`
  reemplaza la escritura con `openpyxl` por `core/fastxlsx.py` (OOXML
  escrito a mano), bajando una transacción a escala mensual de ~2–6s a
  ~0.3s; `d3dedcd` corrige un `StreamlitDuplicateElementId` en la
  pestaña "Mes" de Análisis; `5d9e208` corrige dos bugs reales
  encontrados por el smoke E2E en `scripts/seed_demo.py` (fecha del
  stock inicial fuera del periodo simulado; horas de venta no
  monótonas, que rompían la cadena `stock_antes`/`stock_despues`) y el
  diseño de la verificación de stock; `eaca592` corrige un hallazgo
  real de la revisión V1 (`views/ventas.py` usaba `date.today()` en vez
  de `America/Bogota`) y agrega la primera versión de
  README/DEPLOY/MANUAL_USUARIO/ARQUITECTURA basada en el código ya
  integrado.

## Base de datos inicial publicada

- `8312995` — Siembra y publica `OLATATA_DB.xlsx` inicial en
  `OlaTata-Database`: configuración real del negocio, cero productos,
  ventas o usuarios de ejemplo (`scripts/seed_db.py`).
- `29b966d` — Contrato ejecutable de claves de `CONFIG`
  (`core/config_keys.py` + prueba de contrato) y compuerta de seguridad
  de los datos de demostración (`DEMO=1` obligatorio, nunca puede
  sobrescribir el libro vivo ni publicar a GitHub).
- `49e6708` — Agrega `playwright` a `requirements-dev.txt` para la
  verificación visual real (capturas de pantalla, consola, fuentes).

## Logo, tipografía autoalojada y primer rediseño visual

- `f4bec92` — Genera los assets de marca reales (logo circular,
  favicon, versión monocromática) con `scripts/build_logo_assets.py`.
- `f3f693f` — Autoaloja Inter, Playfair Display y Great Vibes vía
  `theme.fontFaces`.
- `e04eded` — Primer sistema de diseño en `core/ui.py` (`TOKENS`,
  chips, encabezado de página, plantilla de Plotly) + `assets/theme.css`.
- `5f4f0d6` — `app.py`: favicon real, aviso de modo demo, y el
  almacenamiento apunta al libro de demostración cuando `DEMO=1`.
- `5aabfd6` — Corrige el hallazgo `negocio_whatsapp`/`telefono_whatsapp`
  en Ajustes (documentado, no resuelto del lado de `views/vender.py` —
  ver `docs/ARQUITECTURA.md`) y aplica `encabezado_pagina`/`chip_estado`.
- `c8b2cbf` — Verificación visual real con Playwright (capturas en
  `docs/capturas/`).
- `a6c4d4e` — Integración: logo real, tema/tipografía autoalojada,
  componentes de `core/ui.py`, modo demo en `app.py`, capturas.

## Rediseño visual de alto impacto (v2) y hallazgos de seguridad corregidos

- `16e0aed` — Fuente del logo real con inset de 6px, Material Symbols
  Outlined autoalojado, sistema de diseño ampliado en `core/ui.py` +
  `theme.css`.
- `1c0345c` — **Corrige 4 hallazgos CRÍTICOS y 1 ALTO** de la revisión
  de seguridad/atomicidad/dinero (V1–V3), cada uno con una prueba que
  falla antes de la corrección y pasa después.
- `5ef26dd` / `95d6f3b` — Aplica el sistema de tarjetas/hero/KPI a
  `primer_arranque`, `vender`, `ventas`, `inventario`, `analisis` y
  `ajustes` (zona de peligro con borde rojo para acciones destructivas).
- `727729d` — Corrige bloques HTML rotos por líneas en blanco y el
  texto `"nan"` visible en el formulario de Inventario.
- `19970dd` — Corrige el desborde horizontal del sidebar a 390px de
  ancho y agrega las capturas v2 con un script reutilizable.
- `3a28e22` — Corrige pares de contraste por debajo de 4.5:1 y agrega
  pruebas visuales con Playwright (fuentes, consola del navegador,
  desborde).
- `d3dedcd` — (ver arriba, A6) corregido antes de esta ronda de
  capturas v2.
- `05e3030` — Recaptura las 5 pantallas v2/mobile que habían quedado a
  mitad de un rerun de Streamlit.
- `03054b2` — **Integra A5v2**: rediseño visual de alto impacto (mármol
  con aros dorados, tipografía grande centrada, componentes
  consolidados en `core/ui.py`, Material Symbols autoalojado). Estado
  actual de `main` en el momento de escribir esta documentación.

## Base de datos en la nube funcionando + pulido profesional (2026-11-13)

- **CRÍTICO — la base de datos ya no se pierde al reiniciar el servidor.**
  `core/storage.py` descarga `OLATATA_DB.xlsx` desde `OlaTata-Database`
  antes de leer el disco. Antes arrancaba con un libro vacío en cada
  reinicio de Streamlit Cloud y lo publicaba encima de la base real (así
  se perdieron las 12 claves de configuración del negocio en el commit
  `42fc96c`). Nunca publica a ciegas sobre una versión remota que no
  descargó; sin red y sin copia local, muestra "Reintentar" en vez de
  arrancar vacía. Soporta archivos de más de 1 MB.
- **Autorreparación de configuración** (`core/config_inicial.py`): al
  abrir la app se restauran las claves del negocio que falten, sin pisar
  las editadas. `scripts/seed_db.py` usa la misma fuente de verdad.
- **Conflictos de sincronización resueltos desde la app**
  (`core/sincronizacion.py` + Ajustes → Sincronización): "Usar la
  versión de la nube", "Conservar la de este equipo" y "Sincronizar
  ahora", con permisos revalidados y respaldo automático.
- **Indicador de conexión** en la barra lateral (nube al día /
  pendiente / conflicto / modo local).
- **Vender — bug corregido**: "Completar con el total restante" dejaba
  el pago en $ 0, y escanear dos veces el mismo producto no sumaba la
  cantidad (Streamlit ignoraba el valor puesto por el código). Ahora
  las acciones van en callbacks `on_click`. Prueba de regresión con
  `AppTest` en `tests/test_vender_widgets.py`.
- **Login**: logo y aros dorados centrados (antes el logo quedaba corrido
  a la izquierda).
- **Tipografía más clara**: los títulos de pantalla pasan de cursiva
  (Great Vibes) a Playfair Display; la cursiva queda solo para el nombre
  de marca "Ola Tata". Subtítulos centrados, etiquetas más legibles.
- **Tablas legibles** (`core.ui.tabla_amigable`): encabezados en español
  ("Stock actual" en vez de `stock_actual`), dinero en COP, fechas en
  hora de Bogotá, "Sistecrédito"/"WhatsApp" en vez de valores internos.
- **Tarjetas KPI**: misma altura y cifras que se ajustan al ancho de la
  tarjeta (antes "$ 85.000" se salía de la tarjeta a 1366 px).
- Ya no aparece el aviso falso "todavía no se publicó en la nube" en
  modo local.

---

Nota: esta documentación (README, DEPLOY, MANUAL_USUARIO,
ARQUITECTURA, CHANGELOG) se reconstruyó después del commit `03054b2`,
leyendo el código tal como quedó integrado en `main` — no antes.
