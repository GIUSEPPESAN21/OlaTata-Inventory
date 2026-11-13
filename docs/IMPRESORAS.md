# Impresoras y lector de códigos — Ola Tata

Equipos del local (fotos del 2026-11-13):

| Equipo | Qué es | Para qué lo usa la app |
|---|---|---|
| **DigitalPOS de tirilla** (negra, arriba; sticker "When Cutter Locked") | Impresora térmica de recibos de **80 mm** con **cortador automático**, USB | **Recibo de venta** (Vender → "Imprimir recibo") |
| **DigitalPOS de etiquetas** (gris, abajo) | Impresora térmica de etiquetas de escritorio, rollo de **3 etiquetas por fila** | **Etiquetas de precio** (Inventario → Etiquetas) |
| **Lector "BARCODE SCANNER" DigitalPOS** (USB, 5V 0.2A) | Lector de mano que funciona **como un teclado**: escribe el código y oprime Enter | Vender: escanear y agregar al carrito |

## Cómo imprime la app

La app vive en la nube (Streamlit), así que **no habla directo con el USB**:
genera un **PDF al tamaño físico exacto** del papel y el navegador lo manda
a la impresora con su driver de Windows.

- **Etiquetas**: cada página del PDF es **una fila del rollo** (3 etiquetas).
  Con el perfil por defecto la página mide **103 × 25 mm**
  (1 mm de margen + 3 × 32 mm + 2 × 3 mm de separación).
- **Recibo**: página de **80 mm** de ancho y el alto de la venta.
- Plan B para etiquetas: archivo **TSPL** (`.prn`) que se envía directo a la
  impresora sin driver (abajo).

Diseño de la etiqueta nueva, por prioridad: **1) artículo** (mayúsculas,
negrita, hasta 2 líneas), **2) código de barras** (Code128, alto y centrado,
número legible debajo), **3) precio** (lo más grande, formato `$ 98.000`).
Comparada con la anterior, se quitó la fecha, el nombre repetido y el texto
que se salía del borde; las barras son más altas y el precio usa punto de
miles (antes salía `$ 98,000`).

### Qué código lleva cada etiqueta

- Si el producto tiene **código de barras propio** (p.ej. el EAN del
  proveedor), se usa ese.
- Si no, un **código interno numérico de 8 dígitos**: `OT-001367` → `20001367`.
  Es numérico a propósito: barras más anchas en 32 mm y el lector no depende
  del idioma del teclado (con teclado latinoamericano el guion de `OT-001367`
  llega como `OT'001367`; la app igual lo entiende).

## Lista de chequeo para el día de la prueba en el local

Llevar: regla, este documento, un rollo de etiquetas y de tirilla.

### 1. Lector de códigos (5 min)
1. Abrir el Bloc de notas y escanear cualquier código: debe escribirse el
   número y saltar de línea (Enter). Si no salta de línea, configurar el
   lector con el código "Add CR / Enter suffix" de su manual.
2. En la app → **Vender**: sin hacer clic en nada, escanear una etiqueta.
   El cursor ya está en el buscador; el producto debe entrar al carrito.
3. Escanear el mismo producto otra vez: la cantidad debe subir a 2.
4. Si aparecen letras raras (`OT'000001`, `ÑT`), el lector está en otro
   idioma de teclado: la app tolera el guion, pero conviene configurarlo
   en "US keyboard" con el manual.

### 2. Medir el rollo de etiquetas (5 min)
Con la regla, anotar: ancho y alto de UNA etiqueta, espacio entre
etiquetas de la misma fila, espacio entre filas. Comparar con
Inventario → Etiquetas → "Ajustar medidas" (por defecto 32 × 25 mm,
3 mm entre etiquetas, 2 mm entre filas). Si difiere, corregir y
**Guardar como predeterminado**.

### 3. Driver de la impresora de etiquetas (10 min)
1. Windows → Impresoras → DigitalPOS de etiquetas → **Preferencias de
   impresión** → Papel / Stock: crear tamaño **103 × 25 mm** (o el que
   muestre la app en "Papel en el driver"), tipo **etiqueta con separación
   (gap)**, separación 2 mm. Velocidad media, oscuridad media.
2. Calibrar el sensor de separación (botón FEED sostenido o "Calibrar" en
   la herramienta del driver).
3. App → Inventario → Etiquetas → **Hoja de prueba** → Imprimir.
   En el diálogo de Chrome: impresora de etiquetas, **Más opciones →
   Escala: Predeterminada/100 % (NO "Ajustar")**, márgenes **Ninguno**.
4. Los recuadros deben caer dentro de las 3 etiquetas. Si están corridos:
   ajustar **Margen izquierdo**; si se salen por la derecha, revisar la
   separación; si empieza a mitad de etiqueta, recalibrar el sensor.
5. Imprimir 1 fila real y **escanearla** con el lector.

### 4. Plan B: TSPL directo (si el driver escala o recorta)
1. Compartir la impresora de etiquetas en Windows con el nombre `ETIQUETAS`.
2. App → Etiquetas → "Avanzado" → Descargar archivo TSPL (`.prn`).
3. En una ventana de comandos (cmd):
   `copy /b "%USERPROFILE%\Downloads\etiquetas_ola_tata.prn" \\localhost\ETIQUETAS`
4. Si sale en negativo (fondo negro), marcar "Invertir blanco/negro" y repetir.
   Si no imprime nada, la impresora podría no tener modo TSPL: quedarse con el PDF.

### 5. Impresora de tirilla 80 mm (5 min)
1. Hacer una venta de prueba → **Imprimir recibo**.
2. En el diálogo: impresora de tirilla, papel **80 mm** (o "Roll paper
   80 × 297"), escala 100 %, márgenes Ninguno.
3. Debe salir el logo, el detalle y cortar al final. Si queda mucho papel en
   blanco, en el driver elegir "papel continuo / altura según documento".

## Qué anotar si algo falla (para corregirlo después)

- Foto de la etiqueta/recibo impreso junto a la regla.
- Modelo exacto (sticker de abajo de cada impresora) y nombre del driver.
- Las medidas del paso 2 y lo que dice "Papel en el driver".
- Si el lector leyó o no (y qué escribió en el Bloc de notas).
