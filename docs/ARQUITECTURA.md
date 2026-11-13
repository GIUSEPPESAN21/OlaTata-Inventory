# Arquitectura — Ola Tata · Inventario y Ventas

Documento técnico breve. Para la API congelada de cada módulo, ver
`docs/CONTRATOS.md`.

## Vista general

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit (app.py — solo enrutado/sesión)                  │
│    ├─ views/login.py, primer_arranque.py                    │
│    └─ views/{vender,ventas,inventario,analisis,ajustes}.py  │
│         └─ render(ctx: ViewContext)                         │
├─────────────────────────────────────────────────────────────┤
│  core/  (lógica de negocio pura, sin Streamlit)              │
│    permissions.py → requerir(rol, capacidad) en cada función │
│    sales.py / returns.py / inventory.py / monthly_close.py…  │
│    storage.py → Storage.transaction() [lock + atómico]       │
│         ├─ fastxlsx.py  (escritura OOXML rápida)             │
│         └─ archive.py   (libros de cierre, SHA-256, INDEX)   │
├─────────────────────────────────────────────────────────────┤
│  OLATATA_DB.xlsx (disco local)  ←→  GitHub Contents API      │
└─────────────────────────────────────────────────────────────┘
        │ publica (PUT, SHA conocido)      │ publica cierres
        ▼                                   ▼
┌───────────────────────┐          ┌──────────────────────────┐
│ OlaTata-Database       │          │ OlaTata-Archive            │
│ (privado, libro vivo)  │          │ (privado, cierres/AAAA-MM) │
└───────────────────────┘          └──────────────────────────┘
```

## Esquema de datos

El libro vivo (`OlaTata-Database`) es un único `.xlsx` con 13 hojas
(`core/schema.py`, `SHEET_NAMES`), cada una con su propio conjunto de
columnas (`SHEET_COLUMNS`):

| Hoja | Propósito |
|---|---|
| `productos` | Catálogo: nombre, categoría, color, talla/tamaño, proveedor, costo, precio, stock mínimo, código de barras, activo. |
| `stock` | Cantidad actual por `(producto_id, sede_id)` — el saldo vigente, derivado de `movimientos`. |
| `movimientos` | Historial de todo cambio de cantidad (apertura, stock_inicial, entrada, venta, devolución, anulación, ajuste_conteo, ajuste_manual, merma), con `stock_antes`/`stock_despues` — es la fuente de verdad del inventario (R4: `stock = Σ movimientos`). |
| `ventas` | Cabecera de cada venta: número, fecha, canal, cliente, subtotal, descuento, envío, total, estado (completada/anulada), vendedor. |
| `venta_items` | Líneas de producto de cada venta (snapshot de nombre y precios al momento de vender). |
| `pagos` | Uno o más pagos asociados a una venta (permite pago dividido entre métodos). |
| `devoluciones` | Cabecera de cada devolución o cambio: venta de origen, tipo, motivo, método y monto de reembolso. |
| `devolucion_items` | Líneas de producto devuelto, y si vuelven a stock o se marcan como merma. |
| `proveedores` | Catálogo de proveedores (nombre, teléfono, ciudad, notas). |
| `cuadre_caja` | Cuadre diario de caja por sede: base inicial, efectivo esperado vs. contado, diferencia. |
| `usuarios` | Cuentas de acceso: usuario, hash de contraseña, rol, activo, `must_change_password`, `session_epoch` (para invalidar sesiones al cambiar la clave). |
| `config` | Pares clave/valor de configuración del negocio (nombre, WhatsApp, categorías, métodos de pago activos, minutos de sesión, `ultimo_mes_cerrado`, progreso de cierre). |
| `auditoria` | Registro de acciones sensibles (quién, qué, cuándo) — p.ej. cada cierre de mes. |

De estas 13, **7 son transaccionales mensuales**
(`HOJAS_TRANSACCIONALES_MENSUALES`: `ventas`, `venta_items`, `pagos`,
`devoluciones`, `devolucion_items`, `movimientos`, `cuadre_caja`): el
cierre de mes las archiva y las vacía. Las otras 6 (`productos`,
`stock`, `proveedores`, `usuarios`, `config`, `auditoria`) son catálogo
o estado y **nunca** se vacían — en particular, `stock` jamás se
reinicia.

## Flujo del cierre mensual (`core/monthly_close.py`)

`cerrar_mes(storage, rol, year, month)` ejecuta 4 pasos en secuencia.
Es idempotente y a prueba de cortes: si el proceso se interrumpe, la
siguiente llamada vuelve a intentar desde el paso 1 y cada paso es un
no-op seguro (o converge al mismo resultado) si ya se había completado.
La decisión de "¿ya está cerrado este mes?" nunca depende de una
bandera de intención, sino del estado observable real
(`config["ultimo_mes_cerrado"]`).

1. **Construir snapshot** (`_paso1_construir_snapshot`, solo lectura).
   Filtra las 7 hojas transaccionales a las filas del mes `M`
   (usando `America/Bogota` para los límites del mes, vía
   `core.timeutil.month_bounds_utc`), y calcula dos tablas derivadas:
   `stock_cierre` (la cantidad y el costo vigentes de cada producto al
   cierre, tomados del último movimiento con fecha anterior al fin del
   mes — no de la hoja `stock` directamente, para no arrastrar ventas
   de `M+1` que ya se hayan registrado) y `resumen_mes` (KPIs simples:
   ventas completadas/anuladas, ingresos netos, costo vendido, ganancia
   bruta y monto de devoluciones). No escribe nada; si se corta aquí,
   la base viva no cambió y el siguiente intento reconstruye todo desde
   cero.

2. **Publicar** (`_paso2_publicar`). Sube el snapshot como
   `cierres/AAAA-MM.xlsx` a `OlaTata-Archive` (vía
   `storage.archive_put_bytes`) y actualiza `cierres/INDEX.json`
   reemplazando (nunca duplicando) la entrada de ese mismo archivo.
   Guarda un registro informativo en `config["cierre::progreso"]`. Es
   idempotente: reintentar sobreescribe el mismo archivo con el mismo
   contenido determinista.

3. **Verificar** (`_paso3_verificar`). Vuelve a descargar lo que se
   acaba de publicar, recalcula su SHA-256 y compara conteos de filas
   por hoja contra el snapshot original. Si algo no coincide (archivo
   faltante, SHA distinto, hoja faltante o con otro número de filas),
   lanza `CierreVerificacionError` **sin tocar la base viva** — los
   pasos 1 y 2 solo escriben en `OlaTata-Archive`, nunca en el libro
   vivo.

4. **Aplicar** (`_paso4_aplicar`). La única mutación de la base viva,
   dentro de **una sola** `storage.transaction()`: quita del libro vivo
   las filas del mes `M` en las 7 hojas transaccionales, escribe un
   movimiento `"apertura"` por cada producto con `stock_cierre != 0`
   (fechado a las 00:00 Bogotá del día 1 del mes siguiente, para
   preservar el inventario sin reiniciar `stock`), actualiza
   `config["ultimo_mes_cerrado"]` y agrega una fila en `auditoria`. Por
   la regla de atomicidad del proyecto (R6), si algo falla a mitad de
   esta transacción no queda nada a medias.

`cerrar_mes` exige la capacidad `cerrar_mes` (solo rol `admin`, vía
`core.permissions.requerir`), se revalida otra vez justo antes de la
mutación del paso 4, nunca permite cerrar el mes en curso o uno futuro
en Bogotá, y si el mes ya estaba cerrado devuelve de inmediato
`ResultadoCierre(ya_estaba_cerrado=True)` sin repetir ningún trabajo.

## Publicación síncrona a GitHub y control de conflicto por SHA

`core/storage.py` es la única pieza que habla con la red. Fuera de una
`transaction()`, `read_sheet`/`get_config` solo leen lo que ya está en
memoria (cargado una vez desde `OLATATA_DB.xlsx` local). Dentro de una
`transaction()` que sale sin excepción, `_persist_and_publish()` hace,
en orden:

1. **Escritura local atómica** (`_write_local_atomic`): construye el
   `.xlsx` nuevo con `core/fastxlsx.py` en un archivo temporal, copia el
   archivo anterior a `.bak`, y solo entonces `os.replace()` lo
   reemplaza — si el proceso muere a mitad de la escritura, el archivo
   `OLATATA_DB.xlsx` nunca queda a medio escribir (el `os.replace` del
   sistema operativo es la única operación "visible" y es atómica).
2. **Publicación a GitHub** (`_publish_to_github`, solo si
   `sync_enabled`): lee el `.xlsx` recién escrito y lo sube con un
   `PUT /repos/{repo}/contents/{path}`.

El control de conflicto es por **SHA**, el mismo mecanismo que usa la
API de contenidos de GitHub para control de concurrencia optimista:

- Antes de cada `PUT`, `_github_get_sha` pide el SHA **real** actual
  del archivo en GitHub con un `GET`.
- Si `Storage` ya conocía un SHA remoto de una publicación anterior
  propia (`self._known_remote_sha`) y ese SHA **no coincide** con el
  real recién obtenido, significa que algo cambió el archivo remoto
  desde la última publicación de esta misma instancia — se lanza
  `ConflictoDeSincronizacionError` **sin intentar el `PUT`**, se marca
  `sync_status().en_conflicto = True`, y el contenido remoto **nunca se
  sobrescribe**.
- Si no hay conflicto, el `PUT` manda el SHA real como parte del
  payload (requisito de la API de GitHub para actualizar un archivo
  existente) y, si GitHub responde `409`/`422` (carrera transitoria con
  otro proceso), reintenta hasta `_PUT_RACE_RETRIES = 2` veces antes de
  rendirse con el mismo error de conflicto.
- Si GitHub no responde en absoluto (red caída, timeout): la venta ya
  quedó a salvo en el paso 1 (disco local); `_publish_to_github` atrapa
  la excepción, nunca la deja subir hasta `app.py`, y solo incrementa
  `sync_status().pendientes` para que Ajustes → Sincronización lo
  muestre.

**Carga inicial desde GitHub.** Con `sync_enabled`, la primera lectura
descarga `OLATATA_DB.xlsx` desde el repo de datos y fija
`_known_remote_sha` con el sha de esa versión: la nube es la fuente de
verdad y el disco local solo es una copia de trabajo (en Streamlit Cloud
el disco es efímero). Un archivo sidecar `OLATATA_DB.xlsx.sync.json`
recuerda contra qué sha se sincronizó la copia local y si quedaron
cambios sin publicar, para no perderlos tras un reinicio sin red. Si la
nube no responde y no hay copia local, `BaseDeDatosNoDisponibleError`
detiene el arranque (pantalla "Sin conexión con la base de datos" con
botón Reintentar) en vez de arrancar con un libro vacío. Detalle y tabla
de casos en `docs/CONTRATOS.md`.

**Resolución de conflictos (Ajustes → Sincronización).** El admin elige
"Usar la versión de la nube" (`resolver_conflicto_usar_nube`: respalda
la copia local como `*.conflicto-<fecha>.xlsx` y recarga GitHub) o
"Conservar la versión de este equipo" (`resolver_conflicto_conservar_local`:
publica la local encima; la versión remota queda en el historial de
commits). Ambas pasan por `core/sincronizacion.py`, que revalida el
permiso `resolver_conflicto_sync`. "Sincronizar ahora" reintenta publicar
cambios pendientes tras una caída de red.

## Contrato de permisos (`core/permissions.py`)

Dos roles fijos, `admin` y `vendedor` (`core/schema.py:ROLES`), cada uno
con un conjunto de "capacidades" (strings) en `CAPABILITIES`. Dos capas
de aplicación, ninguna opcional:

- **UI** (`views/__init__.py:vistas_visibles_para_rol`): filtra qué
  pantallas aparecen en el menú lateral según una capacidad por vista
  (`VIEWS[i]["permiso"]`). Esto es solo cosmético — oculta un botón, no
  protege nada por sí mismo.
- **Dominio** (`core/*.py`): toda función sensible llama
  `permissions.requerir(rol, "capacidad")` como primera línea, y lanza
  `PermisoDenegadoError` si el rol no la tiene. Esta es la capa real:
  aunque alguien invocara la función directamente (sin pasar por la
  vista), la revalidación ocurre igual.

Capacidad usada por `views/__init__.py` para decidir qué pantallas
muestra el menú, hoy en el código:

| Vista | Capacidad que la habilita | ¿La tiene `vendedor`? |
|---|---|---|
| Vender | `vender` | sí |
| Ventas | `vender` | sí |
| Inventario | `gestionar_inventario` | no |
| Análisis | `ver_analisis_basico` | **sí** |
| Ajustes | `configurar_negocio` | no |

Dentro de Análisis, una segunda capacidad (`ver_analisis_completo`, que
solo tiene `admin`) decide si se muestran costo y ganancia —
`views/analisis.py` oculta esas columnas para quien no la tenga, y
`core/analytics.py` ya omite esas claves del resultado para ese caso
(defensa en profundidad: aunque la vista tuviera un bug de presentación,
el dato sensible nunca llega siquiera al diccionario que se renderiza).

## Contrato de claves de `CONFIG` (`core/config_keys.py`)

La hoja `config` es clave/valor libre (sin columnas fijas más allá de
`clave`/`valor`/fechas), lo que la hace fácil de romper por error de
tipeo. `core/config_keys.py` es la fuente ejecutable de verdad de qué
claves existen de verdad hoy: `tests/test_config_keys_contrato.py`
escanea `app.py`, `core/*.py`, `views/*.py` y `scripts/*.py` buscando
literales `get_config("...")`/`set_config("...")` y falla si el string
no está en `CLAVES_CONOCIDAS` (salvo el prefijo `contador::`, reservado
a `Storage.next_counter`). La tabla completa de claves — quién escribe
cada una, quién la lee y en qué formato — vive en `docs/CONTRATOS.md`,
sección "Claves de CONFIG"; no se repite aquí para no desincronizarse.

**Hallazgo de datos vigente (documentado, no corregido en este cambio):**
`views/ajustes.py` guarda el WhatsApp del negocio en la clave
`negocio_whatsapp`, pero el recibo de venta (`views/vender.py:290`) lee
`telefono_whatsapp` — una clave distinta, sembrada una sola vez por
`scripts/seed_db.py` y que ninguna vista actualiza después. Si un admin
cambia el WhatsApp desde Ajustes, el enlace del recibo sigue apuntando
al número sembrado originalmente. Se mantiene documentado en
`core/config_keys.py` y `docs/CONTRATOS.md` tal como el código se
comporta hoy, no como "debería" comportarse.

## Sistema de diseño (`core/ui.py` + `assets/theme.css` + fuentes autoalojadas)

Tres capas, cada una con una responsabilidad distinta:

1. **Tema nativo de Streamlit** (`.streamlit/config.toml`, sección
   `[theme]`): paleta de marca fija (primario `#C2185B`, fondo
   `#FDEFF0`, barra lateral `#FCE8EC`, etc. — ver `CLAUDE.md` §8),
   radios, tamaño de fuente base, y color de encabezado de tablas. Todo
   lo que el tema nativo ya resuelve **no** se repite en CSS.
2. **`assets/theme.css`** (único archivo CSS del proyecto, inyectado por
   `core.ui.inyectar_identidad_visual()` como un `<style>` embebido, de
   forma idempotente por rerun vía
   `reiniciar_identidad_visual_para_este_rerun()`): solo usa selectores
   estables — `[data-testid="..."]`, clases propias `ot-*`, y
   `[class*="st-key-ot-..."]` (la clase documentada que Streamlit agrega
   a un `st.container(key="ot-...")`) — **nunca** clases autogeneradas
   `.st-emotion-cache-*`, que se rompen entre versiones de Streamlit
   (`tests/test_no_emotion_cache.py` falla si aparece ese patrón en
   cualquier archivo del repo).
3. **`core/ui.py`** (`TOKENS`, única fuente de verdad en Python de la
   paleta/tipografía/escala, usada por los chips, la plantilla de
   Plotly y el CSS inyectado) expone componentes de presentación pura
   — `card`, `hero`, `encabezado_pagina`, `titulo_seccion`,
   `tarjeta_kpi`/`kpi_card`, `chip_estado`, `estado_vacio`,
   `pie_pagina` — sin ningún cálculo de negocio. Ningún emoji en la UI
   (§9 del encargo): los iconos son Material Symbols Outlined
   autoalojados, referenciados como `:material/nombre:` (soporte nativo
   de `st.button`/`st.tabs` desde Streamlit ≥1.36).

Tipografía y los iconos Material se sirven como archivos estáticos
reales bajo `assets/fonts/*.woff2` vía `theme.fontFaces` en
`config.toml` (requiere `server.enableStaticServing = true`): Inter
(400/500/600/700), Playfair Display (600, títulos) y Great Vibes (400,
la firma de marca), más `material-symbols-outlined.woff2` para los
iconos. El logo (`assets/brand/`) se genera de forma reproducible con
`scripts/build_logo_assets.py` a partir de un único JPEG de origen:
recorte circular antialiased con máscara, favicon multi-resolución
(`.ico` + PNG), apple-touch-icon sobre el fondo de marca, y una versión
monocromática para impresión térmica de recibos/etiquetas.
