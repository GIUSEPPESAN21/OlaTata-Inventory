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

## Tablas rediseñadas: solo lo esencial, en el estilo de la marca (2026-11-13)

- Se retiró la cuadrícula tipo hoja de cálculo (`st.dataframe`, dibujada
  en canvas: sin estilo de marca, textos cortados, columnas técnicas) de
  toda la app. Componentes nuevos en `core/ui.py`, con todo texto escapado:
  - `fila_html` + filas tipo tarjeta: **Ventas** (qué se vendió, cliente,
    N.º/fecha/pago, total; "Ver" abre el detalle justo debajo),
    **Productos** (nombre, categoría/código, precio y chip de stock;
    "Editar" abre el formulario debajo) y **Usuarios** ("Gestionar" abre
    editar/clave/estado debajo). Paginación "Mostrar más".
  - `barras_ranking`: Análisis por método de pago, canal y categoría.
  - `tabla_html`: ventas del día, stock sin ventas, registro de seguridad,
    importación e integridad; en celular cada fila se vuelve tarjeta.
  - Etiquetas: buscador de productos + lista con cantidades.
- En celular el menú lateral se cierra solo al elegir una opción, y las
  cifras de Ventas van en una sola franja.
- Descargas diferidas (el archivo se genera al pulsar) y sin recargar la
  página al descargar; elimina errores 404 en la consola.

## Fluidez: sin saltos ni animaciones, Vender y Ventas en tiempo real (2026-11-13)

- **Bug principal corregido**: las tarjetas recibían una clave NUEVA en
  cada clic (contador global que nunca se reiniciaba), así que Streamlit
  las reconstruía: se cerraban desplegables, se perdía el foco y la
  pantalla saltaba. Ahora la clave es estable por pantalla.
- **Salto al buscador corregido**: el enfoque automático para el lector
  movía la página hasta arriba al pulsar cualquier botón; ahora enfoca sin
  desplazar y solo si no estás escribiendo en otro campo.
- **Pestañas con memoria** (Inventario, Análisis, Ajustes): conservan la
  pestaña elegida y solo ejecutan la visible (más rápido: antes corrían
  todas en cada clic, incluido el PDF de etiquetas).
- **Sin animaciones** ni "atenuado" de pantalla al hacer clic.
- **Vender rediseñado**: búsqueda en tiempo real (sin Enter) por nombre,
  código o código de barras, con precio y existencias; el lector agrega
  solo; dos columnas con resumen fijo; indicador de pago de altura fija.
- **Ventas rediseñado**: tabla con todas las ventas visibles, búsqueda en
  vivo (número, cliente, teléfono, producto, código, vendedor), cifras del
  período y detalle al tocar una fila con reimprimir/editar/anular/devolver.
- **Pie de página**: "Desarrollado por SAVA" con logo mínimo, Joseph
  Sánchez y 322 207 4527 (enlace a WhatsApp). Usa
  `assets/brand/sava-logo.png` cuando exista.

## 3 artículos de prueba y "Empezar con el inventario real" (2026-11-13)

- Los datos de prueba crean 3 productos ("[PRUEBA] Bolso tote rosa",
  "Cartera de cuero negra", "Billetera mini dorada") con stock.
- **Empezar con el inventario real** (`core/inicio_produccion.py`, solo
  maestro, UNA vez): vacía productos, stock, movimientos, ventas, pagos,
  devoluciones, proveedores y cuadres, y quita los usuarios de prueba.
  Conserva usuarios reales, configuración y auditoría. Queda registrada la
  fecha (`produccion_iniciada`) y desde entonces no se repite ni se crean
  datos de prueba.

## Rol maestro, edición de usuarios y ventas, datos de prueba (2026-11-13)

- **Rol "maestro"** (`core/permissions.py`): todo lo del administrador y
  del vendedor (calculado, nunca se queda atrás) + editar usuarios, editar
  ventas y datos de prueba. El primer administrador del negocio
  (`giuseppesan`) pasa a maestro automáticamente al abrir la app.
  Ningún administrador puede desactivarlo, restablecer su clave ni editarlo.
- **Editar usuarios** (solo maestro): nombre, usuario y rol; si cambia el
  usuario o el rol se cierran sus sesiones.
- **Editar datos de una venta** (solo maestro): cliente, teléfono, canal,
  envío y nota. Productos y montos NO (para eso: anular o devolución).
  La venta ahora muestra teléfono, envío y nota.
- **Datos de prueba** (Ajustes → Datos de prueba, solo maestro): crea
  prueba.admin, prueba.vendedor, "[PRUEBA] Bolso de prueba" y una venta
  simulada con las funciones reales; "Eliminar" lo quita todo en una sola
  transacción sin tocar datos reales (y se niega si hay una venta real
  mezclada).
- Todo queda en el registro de seguridad.

## Títulos uniformes, guías de uso y seguridad reforzada (2026-11-13)

- **Diseño**: todos los títulos centrados (página, subtítulo, secciones,
  pestañas y su descripción), un poco más grandes; aros del estado vacío
  alineados con su icono. Verificado midiendo en el navegador: 0 px de
  desvío en las 16 pantallas/pestañas.
- **Barra superior de Streamlit oculta** (Share, estrella, lápiz, GitHub,
  ⋮), conservando el botón para reabrir la barra lateral, que en 1.66 vive
  dentro de esa barra.
- **Guías "¿Cómo se usa?"** en cada pantalla y pestaña (`core/guias.py`).
- **Seguridad** (`core/seguridad.py`, `docs/SEGURIDAD.md`): Pillow 13.0
  (76 vulnerabilidades corregidas) y `pip-audit` en CI; política de claves
  de 10+ caracteres; pausa creciente ante logins fallidos; sesión máxima de
  12 h; "Restablecer clave" para el admin; no se puede desactivar la propia
  cuenta ni al último admin; registro de seguridad (auditoría); nombres de
  usuario restringidos; escape de Markdown en textos libres; navegador sin
  trazas de error (`showErrorDetails = "none"`).
- CI: descarga Chromium para las pruebas visuales (antes fallaban siempre).

## Impresión de etiquetas, recibos y lector de códigos (2026-11-13)

- **Etiquetas físicas** (`core/etiquetas.py`): PDF al tamaño real del rollo
  de la impresora DigitalPOS (por defecto 3 por fila de 32 × 25 mm, 203 dpi),
  una página por fila. Prioridad: artículo, código de barras, precio
  ("$ 98.000"). Barras Code128 dibujadas con módulos enteros (nítidas en
  térmico); código interno numérico `20xxxxxx` para productos sin código
  propio. Perfiles predefinidos + medidas ajustables guardadas en CONFIG
  (`etiquetas_perfil`), hoja de prueba de calibración y archivo TSPL como
  plan B. Pruebas que DECODIFICAN cada etiqueta con zxing-cpp.
- **Recibo de 80 mm** (`core/recibo_impreso.py`) para la impresora de
  tirilla con cortador: logo, ítems, totales, pagos y mensaje del negocio.
- **Botón "Imprimir"** (`core.ui.boton_imprimir_pdf`): abre el diálogo de
  impresión del sistema con el PDF a tamaño real; descarga como respaldo.
- **Lector USB**: el cursor queda listo en el buscador de Vender (se puede
  escanear sin tocar el mouse); la búsqueda entiende el código interno de
  la etiqueta y el guion que el teclado latino convierte en apóstrofo.
- Guía para el día de instalación: `docs/IMPRESORAS.md`.

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
