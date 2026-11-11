# Ola Tata · Inventario y Ventas

Aplicación de inventario, punto de venta y análisis para
**Ola Tata – Bolsos y Accesorios** (Buga / Tuluá, Colombia).

Desarrollado por **SAVA**.

> Este repositorio está en construcción por hitos (ver `CHANGELOG.md`
> una vez exista). La documentación completa de instalación, despliegue
> y manual de usuario se agrega al cierre de los hitos correspondientes.

## Stack

Python 3.12 (CI) / 3.11 (desarrollo local) · Streamlit · pandas ·
openpyxl · plotly · bcrypt · python-barcode · Pillow.

## Estructura

```
app.py            # enrutado y login únicamente
views/            # una vista por pantalla (vender, ventas, inventario, analisis, ajustes)
core/             # lógica de negocio pura, sin Streamlit, 100% testeable
tests/            # pytest
scripts/          # utilidades (smoke E2E, etc.)
assets/           # logo y estáticos
.streamlit/       # tema y configuración
```

## Repos relacionados

- `OlaTata-Database` — base viva (mes en curso), privado, sin código.
- `OlaTata-Archive` — archivo inmutable de meses cerrados, privado, sin código.
