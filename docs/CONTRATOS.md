# Contratos congelados (M1)

Esta página documenta la API pública de los módulos base que **ningún**
subagente debe modificar directamente: `core/schema.py`, `core/money.py`,
`core/timeutil.py`, `core/storage.py`, `core/permissions.py`,
`core/auth.py`, `core/config.py`, `core/excel_safe.py`,
`views/__init__.py` y `requirements*.txt`.

**Regla:** si un módulo de dominio (A1-A6) necesita una columna, una
capacidad o una dependencia nueva, la PIDE en su informe final. No la
agrega por su cuenta. El agente principal evalúa el pedido, lo aplica
aquí si es razonable, y avisa al resto.

## `core/schema.py`

- `SHEET_NAMES: list[str]` — las 13 hojas, en orden.
- `SHEET_COLUMNS: dict[str, list[str]]` — columnas exactas por hoja (§5).
- `columnas(sheet: str) -> list[str]` — copia independiente de las columnas.
- Constantes de hoja: `PRODUCTOS, STOCK, MOVIMIENTOS, VENTAS, VENTA_ITEMS,
  PAGOS, DEVOLUCIONES, DEVOLUCION_ITEMS, PROVEEDORES, CUADRE_CAJA,
  USUARIOS, CONFIG, AUDITORIA`.
- Vocabularios válidos: `TIPOS_MOVIMIENTO`, `ESTADOS_VENTA`,
  `METODOS_PAGO`, `CANALES_VENTA`, `ROLES`, `SEDE_PRINCIPAL = "principal"`.
- `HOJAS_TRANSACCIONALES_MENSUALES` — las que el cierre de mes archiva y
  vacía (ventas, venta_items, pagos, devoluciones, devolucion_items,
  movimientos, cuadre_caja). `stock`, `productos`, `proveedores`,
  `usuarios`, `config`, `auditoria` NUNCA se vacían.

## `core/money.py` (R1: dinero siempre entero)

- `parse_pesos(value) -> int` — acepta int/float-entero/str formateada
  ("$ 1.250.000"); **lanza `DineroInvalidoError`** si hay decimales.
- `format_cop(value: int) -> str` — `"$ 1.250.000"`.
- `round_half_up_pesos(value) -> int` — redondeo mitad arriba (costo
  promedio ponderado, R5).
- `format_percent(numerador, denominador, decimales=1) -> str` —
  `Decimal`, redondeo mitad arriba; `"—"` si `denominador == 0`.

## `core/timeutil.py` (R2: todo corte en America/Bogota)

- `BOGOTA: ZoneInfo`, `UTC: timezone`.
- `now_utc() -> datetime` aware en UTC.
- `to_iso_utc(dt) -> str` / `parse_iso_utc(texto) -> datetime`.
- `local_date(dt_utc) -> date` — fecha calendario en Bogotá de un
  datetime UTC (probado: 23:30 Bogotá del día N → `date` = día N, aunque
  en UTC ya sea día N+1).
- `month_bounds_utc(year, month) -> (inicio, fin)` — límites `[inicio,
  fin)` del mes calendario de Bogotá, en UTC.
- `week_bounds_utc(any_local_date) -> (inicio, fin)` — semana lunes→
  domingo de Bogotá, límites `[inicio, fin)` en UTC.
- `start_of_month_local(d) -> date`.

## `core/storage.py` (R1: transacción atómica + sync + archive)

```python
Storage(local_path, github_repo=None, github_token=None,
        archive_repo=None, sync_enabled=True)

with storage.transaction() as tx:
    df = tx.read_sheet(schema.VENTAS)
    tx.write_sheet(schema.VENTAS, df_modificado)
    tx.set_config("clave", "valor")
    numero = tx.next_counter("ventas", reset_key="2026-11")  # atómico

storage.read_sheet(name) -> pd.DataFrame          # copia, fuera o dentro de transacción
storage.get_config(clave, default=None) -> str|None
storage.sync_status() -> SyncStatus(pendientes, en_conflicto, ultimo_error, ultimo_sync_utc)
storage.archive_get_bytes(path) -> bytes|None
storage.archive_put_bytes(path, content: bytes, message: str) -> dict

# Agregado (coordinador, 2026-11-13) — ver "Carga desde la nube" abajo:
storage.sincronizar_ahora() -> SyncStatus              # reintenta publicar pendientes
storage.resolver_conflicto_usar_nube() -> SyncStatus   # recarga GitHub, respalda la local
storage.resolver_conflicto_conservar_local() -> SyncStatus  # publica la local encima
storage.sha_remoto_cargado: str | None                 # informativo
BaseDeDatosNoDisponibleError                           # sin red y sin copia local
```

Las tres operaciones de sincronía NO revalidan permisos (capa de datos):
la UI debe llamarlas a través de `core/sincronizacion.py`
(`sincronizar_ahora(storage, rol)`, `resolver_conflicto(storage, rol,
opcion)`), que exige `resolver_conflicto_sync` como primera línea.

### Carga desde la nube (corrección crítica, 2026-11-13)

Antes, `Storage` solo leía el archivo LOCAL. En Streamlit Community
Cloud el disco es efímero: tras cada reinicio la app arrancaba con un
libro vacío y la primera transacción sobrescribía la base real en GitHub
(así se perdieron las 12 claves de CONFIG en producción, commit
`42fc96c` de OlaTata-Database). Ahora, con `sync_enabled`, la primera
lectura (`_ensure_loaded`) descarga `OLATATA_DB.xlsx` de GitHub ANTES de
mirar el disco:

| Situación al abrir | Resultado |
|---|---|
| Remoto existe, local sin cambios pendientes | se usa el remoto (la local distinta se respalda como `*.local-<fecha>.xlsx`) |
| Local con cambios sin publicar sobre ese MISMO sha remoto | se conserva la local, queda pendiente de publicar |
| Remoto no existe (404) | base nueva (local si existe, si no vacía) |
| Sin red, hay copia local | trabaja sin conexión; publica luego comparando contra el sha del sidecar |
| Sin red, sin copia local | `BaseDeDatosNoDisponibleError` (la app muestra "Reintentar"; NUNCA arranca vacía) |

El sha de la última sincronización y si hay cambios pendientes se guarda
en un archivo sidecar `OLATATA_DB.xlsx.sync.json` (en `.gitignore`).
Archivos de más de 1 MB se descargan con `Accept: application/vnd.github.raw`
(la API de contenidos no incluye `content` en base64 por encima de 1 MB).

Reglas duras:
- `write_sheet` / `set_config` / `next_counter` **solo** dentro de
  `transaction()` (lanzan `RuntimeError` si no).
- Si el bloque de `transaction()` lanza una excepción, NINGÚN cambio se
  persiste (ni en memoria ni en disco) — R6.
- Al salir sin excepción: escritura atómica a disco (archivo temporal +
  `os.replace`, con respaldo `.bak` del anterior) y publicación síncrona
  a GitHub.
- Publicación: compara el SHA remoto conocido contra el SHA remoto real
  antes de escribir — también cuando el conocido es `None` y el remoto
  SÍ existe (nunca se sobrescribe a ciegas una base que esta instancia
  no descargó). Si cambiaron → `ConflictoDeSincronizacionError`,
  **nunca sobrescribe**, marca `sync_status().en_conflicto = True`. Ante
  409/422 transitorio reintenta hasta 2 veces. Si no hay red: la venta
  YA quedó a salvo en disco local; solo sube `sync_status().pendientes`.
- Toda celda de texto se fuerza a tipo texto (`inlineStr`) al escribir el
  .xlsx: un valor como `"=1+1"` nunca se guarda como fórmula (R11).
- **Escritura real: `core/fastxlsx.py`** (ya implementado, no openpyxl
  directo). A6 midió que escribir con `openpyxl` normal (incluso en modo
  `write_only`) tardaba ~2-5s por `transaction()` incremental a escala de
  un mes de alto volumen (1500-3000 ventas) — muy por encima del
  presupuesto de 500ms del §11. La causa es el overhead por-celda de la
  API de openpyxl (confirmado con `cProfile`: ~141k celdas ≈ 4s solo en
  la serialización XML celda por celda). `core/fastxlsx.py` construye el
  OOXML a mano con `str.join` (texto siempre `t="inlineStr"`, nunca
  fórmula) y baja esto a ~0.3s a la misma escala — dentro del
  presupuesto. `core/storage.py._write_workbook` delega en
  `fastxlsx.write_workbook`; la LECTURA sigue usando
  `pandas.read_excel(engine="openpyxl")` normal (no era el cuello de
  botella). Ver `tests/test_fastxlsx.py` y `tests/test_perf_budgets.py`
  para el benchmark y las pruebas de round-trip de tipos.

## Claves de `CONFIG` (clave/valor libre, ver `core/schema.py:CONFIG`)

**Fuente ejecutable de verdad: `core/config_keys.py`.**
`tests/test_config_keys_contrato.py` escanea `app.py`, `core/*.py`,
`views/*.py` y `scripts/*.py` buscando llamadas a `get_config("...")` /
`set_config("...")` con una clave **literal**, y falla si esa clave no
está en `core/config_keys.CLAVES_CONOCIDAS` (ni es un contador interno,
ver abajo). Añadir una clave nueva: documentarla aquí Y en
`core/config_keys.py` en el mismo cambio, o la prueba de contrato falla.

Estas claves **reemplazan** a las nombradas en la especificación de
diseño original (`nombre_negocio`, `categorias`, `metodos_pago_activos`,
`mensaje_recibo`) — son las que el código de este repo lee/escribe de
verdad hoy.

### Negocio (editables desde Ajustes → pestaña "Negocio", `views/ajustes.py`)

| Clave | Escrita por | Leída por | Formato |
|---|---|---|---|
| `negocio_nombre` | Ajustes | Ajustes (valor por defecto del formulario) | texto libre |
| `negocio_whatsapp` | Ajustes | Ajustes (valor por defecto del formulario) | texto libre |
| `negocio_mensaje_recibo` | Ajustes | Ajustes (valor por defecto) | texto libre, máx. 4000 |
| `negocio_categorias` | Ajustes | Ajustes (valor por defecto); `views/inventario.py` deriva el filtro de categorías de la hoja `productos`, no de esta clave | lista separada por `"\|"`, sin vacíos |
| `negocio_metodos_pago_activos` | Ajustes | Ajustes (valor por defecto) | subconjunto de `schema.METODOS_PAGO` separado por `"\|"` |

### Operación

| Clave | Escrita por | Leída por | Formato |
|---|---|---|---|
| `sesion_minutos` | Ajustes, `scripts/seed_db.py` | `app.py` (expiración de sesión) | entero en texto, minutos |
| `permitir_vender_sin_stock` | `scripts/seed_db.py` (ninguna vista la escribe hoy — ver hallazgo abajo) | `core/sales.py` (permite vender con stock insuficiente) | `"true"` / `"false"` |
| `ultimo_mes_cerrado` | `core/monthly_close.py` | `core/monthly_close.py` (idempotencia del cierre) | `"YYYY-MM"` o ausente |
| `telefono_whatsapp` | `scripts/seed_db.py` (ninguna vista la escribe hoy — ver hallazgo abajo) | `views/vender.py` (enlace de WhatsApp del recibo) | dígitos, con o sin `+`/espacios |
| `cierre::progreso` | `core/monthly_close.py` (en cada paso del cierre) | solo informativo para un admin; la reanudación NUNCA depende de esta clave, sino del estado observable (`ultimo_mes_cerrado` + releer lo archivado) | JSON `{year, month, paso, archivo, sha256}` |
| `etiquetas_perfil` | Inventario → Etiquetas (`core.etiquetas.guardar_perfil`, solo admin) | `core.etiquetas.cargar_perfil` (si falta o está dañado: 3 por fila · 32 × 25 mm) | JSON `{nombre, ancho_mm, alto_mm, columnas, separacion_mm, margen_izq_mm, gap_vertical_mm, dpi}` |

**Hallazgo (no corregido aquí; lo cierra quien edite `views/ajustes.py` o
`views/vender.py`):** Ajustes guarda el WhatsApp del negocio en
`negocio_whatsapp`, pero el recibo de venta (`views/vender.py:255`) lee
`telefono_whatsapp` — una clave distinta que ninguna vista actualiza. Si
un admin cambia el WhatsApp desde Ajustes, el enlace del recibo sigue
usando el valor sembrado por `scripts/seed_db.py` y nunca se actualiza.

### Informativas

Sembradas por `scripts/seed_db.py`; ningún módulo las lee todavía (se
reservan para un futuro encabezado/tema que las necesite):

`instagram`, `ciudades`, `zona_horaria`, `moneda`.

### Contadores internos (no son "claves de negocio")

`Storage.next_counter(nombre, reset_key=None)` guarda su estado en
`contador::<nombre>::<reset_key o 'global'>` (p.ej.
`contador::ventas::2026-11`). Son un detalle de implementación del
primitivo de `core/storage.py`, nunca se leen/escriben por nombre
literal fuera de `next_counter` mismo — por eso no están enumerados uno
a uno en `CLAVES_CONOCIDAS`; la prueba de contrato los reconoce por el
prefijo `contador::`.

## `scripts/seed_demo.py` — compuerta de seguridad de los datos de demo

Genera un libro 100% ficticio para explorar/capturar la app, NUNCA datos
reales. Reglas duras (ver `tests/test_seed_demo_compuerta.py`):

- Requiere `DEMO=1` exacto en el entorno. Sin eso, `main()` termina con
  `SystemExit` antes de tocar disco — ningún archivo se escribe.
- Rechaza cualquier ruta de salida cuyo nombre sea `OLATATA_DB.xlsx`
  (sin distinguir mayúsculas), sin importar la carpeta. Por defecto
  escribe en `demo/OLATATA_DEMO.xlsx` (en `.gitignore`).
- Usa `_AlmacenDemoSoloLocal` (subclase de `core.storage.Storage` local
  a este script): el constructor fuerza `github_repo=None,
  github_token=None, sync_enabled=False` sin importar las variables de
  entorno reales (p.ej. si la app de producción ya tiene `GITHUB_TOKEN`
  configurado en la misma máquina), y `_publish_to_github` se
  sobreescribe para **lanzar** `RuntimeError` si alguna vez se invocara
  — defensa en profundidad, no solo "no se llama".
- `core.demo_mode.render_aviso_datos_prueba()` (módulo nuevo, no
  `app.py`/`core/ui.py`) pinta el aviso permanente "DATOS DE PRUEBA"
  cuando `DEMO=1`. A5 lo integra con una línea al inicio de `app.py`,
  antes de enrutar a cualquier vista.

## `core/permissions.py` (§10: revalidado en core/, no solo en la UI)

```python
ADMIN = "admin"
VENDEDOR = "vendedor"
CAPABILITIES: dict[str, frozenset[str]]
tiene_capacidad(rol: str, capacidad: str) -> bool
requerir(rol: str, capacidad: str) -> None   # lanza PermisoDenegadoError
```

Capacidades iniciales (ampliables bajo pedido):
- **admin**: `vender, ver_ventas_todas, anular_venta, devolucion_cambio,
  ver_costos, ver_analisis_basico, ver_analisis_completo, gestionar_inventario, ajustar_stock,
  importar_inventario, etiquetas, verificar_integridad, cuadre_caja,
  cerrar_mes, gestionar_usuarios, resolver_conflicto_sync,
  descargar_respaldo, configurar_negocio`.
- **vendedor**: `vender, ver_ventas_propias, devolucion_cambio,
  cuadre_caja, ver_analisis_basico`.

**Toda** función de dominio sensible en `core/` (anular venta, ajustar
stock, cerrar mes, crear usuario, etc.) debe llamar `requerir(rol, ...)`
como primera línea.

## `core/auth.py`

```python
hash_password(plano) -> str            # bcrypt, trunca a 72 bytes
verify_password(plano, hash) -> bool
login(storage, usuario, password) -> LoginResultado(ok, usuario, motivo)
crear_usuario(storage_tx, *, nombre, usuario, password_plano, rol,
              must_change_password=True) -> id   # dentro de transaction()
cambiar_password(storage_tx, usuario_id, password_nuevo_plano) -> None  # incrementa session_epoch
validar_sesion(storage, usuario_id, session_epoch, ultima_actividad_utc,
               minutos_inactividad=None) -> bool
```

Límite de intentos (`MAX_INTENTOS = 5`, bloqueo `BLOQUEO_SEGUNDOS = 900`)
vive en memoria de proceso (no en la hoja `usuarios`): un redeploy limpia
los bloqueos, lo cual es aceptable (no es un invariante de negocio).
Mensaje de error SIEMPRE genérico ("Usuario o contraseña incorrectos.");
`login()` corre `verify_password` contra un hash ficticio incluso cuando
el usuario no existe, para no filtrar por tiempo de respuesta.

## `core/config.py`

- `safe_secret(key, default=None) -> str|None` — lee `st.secrets`, nunca
  truena si no hay `secrets.toml`; fallback a variable de entorno.
- `DEFAULT_DB_PATH = "OLATATA_DB.xlsx"`.

## `core/excel_safe.py` (R11)

- `excel_safe(value, max_length=2000, field_name="texto") -> str` — quita
  caracteres de control (conserva `\n`/`\t`), recorta espacios, valida
  largo. El texto **nunca** se trunca ni se reinterpreta: `"=1+1"` sale
  igual que entró (la protección contra fórmula ocurre en
  `storage.py` al escribir la celda).
- `csv_safe(value) -> str` — antepone `'` si el texto empieza por
  `=, +, -, @` (inyección de fórmulas en CSV exportado).

## `views/__init__.py`

```python
VIEWS: list[dict]  # [{"key","label","icon","module","permiso"}, ...] — máx. 5 (§6)
ViewContext(storage, usuario, rerun)   # lo que recibe cada vista
vistas_visibles_para_rol(rol) -> list[dict]
```

Cada `views/<nombre>.py` expone `def render(ctx: ViewContext) -> None`.
`app.py` (solo A5) itera `VIEWS`, importa el módulo y llama `render(ctx)`
— nunca necesita cambiar cuando A1-A4 llenan su vista.

## Dependencias fijadas (`requirements.txt` / `requirements-dev.txt`)

Tomadas de `UNIMINUTO-Lab-Inventory` (base de arquitectura) y verificadas
con instalación real en este entorno (Python 3.11 local; CI valida 3.12):

```
streamlit==1.66.1  pandas==3.1.0  openpyxl==3.1.5  plotly==7.1.0
bcrypt==5.0.0  python-barcode==0.16.1  Pillow==11.3.0  requests==2.34.2
tzdata (solo Windows)
--- dev ---
pytest==9.2.0  pytest-cov==7.1.0  ruff==0.17.3  playwright==1.65.1
```

`playwright` se añadió (continuación §4, verificación visual E1-E3) para la
verificación visual real con Chromium headless (capturas de pantalla y
smoke de fuentes/consola). Tras instalarlo corre `playwright install
chromium` una vez por entorno (no es un paquete pip, no va en
`requirements-dev.txt`).

`requests` se añadió fuera de la lista original del encargo porque
`core/storage.py` lo necesita para hablar con la API de GitHub (el lab
lo usa con el mismo propósito). Si algún agente necesita otra
dependencia (p.ej. una librería de PDF para etiquetas), **pídela en tu
informe en vez de instalarla**: Pillow ya permite guardar imágenes como
PDF multipágina (`Image.save(..., "PDF", save_all=True)`), que debería
bastar para `labels_ot.py` sin añadir `reportlab`/`fpdf2`.
