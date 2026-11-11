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
```

Reglas duras:
- `write_sheet` / `set_config` / `next_counter` **solo** dentro de
  `transaction()` (lanzan `RuntimeError` si no).
- Si el bloque de `transaction()` lanza una excepción, NINGÚN cambio se
  persiste (ni en memoria ni en disco) — R6.
- Al salir sin excepción: escritura atómica a disco (archivo temporal +
  `os.replace`, con respaldo `.bak` del anterior) y publicación síncrona
  a GitHub.
- Publicación: compara el SHA remoto conocido contra el SHA remoto real
  antes de escribir. Si cambiaron → `ConflictoDeSincronizacionError`,
  **nunca sobrescribe**, marca `sync_status().en_conflicto = True`. Ante
  409/422 transitorio reintenta hasta 2 veces. Si no hay red: la venta
  YA quedó a salvo en disco local; solo sube `sync_status().pendientes`.
- Toda celda de texto se fuerza a `data_type="s"` al escribir el .xlsx:
  un valor como `"=1+1"` nunca se guarda como fórmula (R11).
- **Conocido, no implementado en M1:** no se usa un `fastxlsx.py` que
  escriba OOXML a mano (como el del lab) — se usa `openpyxl` directo.
  Es correcto pero más lento en libros grandes. Si los presupuestos de
  rendimiento del §11 (confirmar venta < 500ms local) no se cumplen con
  datos reales de varios meses, ese es el primer lugar a optimizar. A6
  debe medirlo en el smoke E2E y reportarlo si es un problema real.

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
pytest==9.2.0  pytest-cov==7.1.0  ruff==0.17.3
```

`requests` se añadió fuera de la lista original del encargo porque
`core/storage.py` lo necesita para hablar con la API de GitHub (el lab
lo usa con el mismo propósito). Si algún agente necesita otra
dependencia (p.ej. una librería de PDF para etiquetas), **pídela en tu
informe en vez de instalarla**: Pillow ya permite guardar imágenes como
PDF multipágina (`Image.save(..., "PDF", save_all=True)`), que debería
bastar para `labels_ot.py` sin añadir `reportlab`/`fpdf2`.
