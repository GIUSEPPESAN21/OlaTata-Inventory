# Assets de marca · Ola Tata

Todos los archivos de esta carpeta se generan con
`scripts/build_logo_assets.py` a partir del logo oficial
(`C:\Users\LENOVO\Downloads\olatata-logo.jpg`, JPEG 690x690 px). No se
editan a mano — para regenerarlos, vuelve a correr el script.

| Archivo | Tamaño | Dónde se usa |
|---|---|---|
| `olatata-logo-original.png` | 690x690, RGB | Copia intacta de referencia (nunca se modifica); fuente para regenerar todo lo demás y para la prueba de hash en `tests/test_assets.py`. |
| `olatata-logo.png` | 512x512, RGBA | Recorte circular base, fondo transparente, 3 px de inset para quitar el halo gris del cuadrado original. Fuente de todos los derivados. Login y primer arranque (160-200 px), encabezado de Excel exportado (hoja Resumen). |
| `olatata-logo-256.png` | 256x256, RGBA | Derivado circular — vistas previas, documentación. |
| `olatata-logo-128.png` | 128x128, RGBA | Derivado circular — tarjetas/documentación a tamaño medio. |
| `olatata-logo-64.png` | 64x64, RGBA | Avatar de la barra lateral (72 px objetivo: usar este y dejar que el navegador escale ligeramente, o `olatata-logo-128.png` reducido). |
| `favicon.ico` | 16/32/48 multi-resolución | `page_icon` de Streamlit / favicon del navegador. |
| `favicon-32.png` | 32x32, RGBA | Favicon en formato PNG simple (fallback para navegadores que no leen bien `.ico`). |
| `apple-touch-icon.png` | 180x180, RGB (sin alfa) | Ícono para pantalla de inicio en iOS, compuesto sobre el fondo de marca `#FDEFF0` (los dispositivos Apple no respetan transparencia en este ícono). |
| `olatata-logo-mono.png` | 512x512, escala de grises umbralizada (blanco y negro puro) | Recibo de venta (impresión térmica), donde el color no se imprime y el contraste debe ser máximo. Probado legible a 200 px. |

## Verificación automática

`tests/test_assets.py` comprueba:
- Que todos los archivos de esta tabla existen.
- Tamaños (ancho x alto) exactos.
- `alpha == 0` en las 4 esquinas de cada PNG circular (confirma que el
  recorte quitó el halo gris del cuadrado original).
- Que `olatata-logo-original.png` sigue siendo exactamente el mismo
  contenido de píxeles que el archivo de origen (hash de los datos
  decodificados, no del archivo — JPG y PNG nunca van a compartir bytes
  idénticos, pero sí deben compartir los mismos píxeles).

## Reglas de uso (ver `core/ui.py` y `docs/CONTRATOS.md`)

Nunca estirar ni deformar: conservar proporción 1:1 siempre. A menos de
56 px, usar solo el círculo (avatar) sin intentar que el texto interior
sea legible — a esa escala el texto del logo deja de leerse y confunde
en vez de aportar identidad.
