# Arquitectura — Ola Tata · Inventario y Ventas

Documento técnico breve. Para la API congelada de cada módulo, ver
`docs/CONTRATOS.md`.

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
