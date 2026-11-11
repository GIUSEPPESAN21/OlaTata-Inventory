"""Escritura rápida de .xlsx: construye el OOXML a mano (sin el overhead
por-celda de openpyxl), evitando el problema de rendimiento medido por A6:
~2s por transacción incremental con un libro de un mes de alto volumen
(1500 ventas / 3750 items), muy por encima del presupuesto de 500ms (§11).

Es el equivalente de `core/fastxlsx.py` del lab de referencia (adaptado,
no copiado): construye el XML de cada hoja con `str.join` en vez de la
API de celdas de openpyxl, que es ~10-50x más rápido en libros grandes.

`core/storage.py` es el único módulo que llama a `write_workbook`. La
LECTURA sigue usando `pandas.read_excel(engine="openpyxl")` normal: el
archivo que este módulo produce es OOXML válido estándar, cualquier
lector lo abre igual — el cuello de botella medido estaba solo en la
ESCRITURA.

CONTRATO CONGELADO (ver docs/CONTRATOS.md) — detalle de implementación
de `core/storage.py`, no una API que otros módulos deban llamar directo.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import pandas as pd

_CONTENT_TYPES_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)

_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _col_letter(idx0: int) -> str:
    """Índice de columna (0-based) -> letra de columna Excel (0->A, 25->Z, 26->AA)."""
    idx = idx0 + 1
    letras = []
    while idx > 0:
        idx, resto = divmod(idx - 1, 26)
        letras.append(chr(ord("A") + resto))
    return "".join(reversed(letras))


def _cell_xml(ref: str, value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, str):
        if value == "":
            return ""
        texto = escape(value)
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{texto}</t></is></c>'
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value):  # NaN
            return ""
        return f'<c r="{ref}"><v>{value!r}</v></c>'
    # Cualquier otro tipo (p.ej. pandas Timestamp residual): texto seguro.
    texto = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{texto}</t></is></c>'


def _sheet_xml(df: pd.DataFrame) -> str:
    columnas = list(df.columns)
    partes: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
    ]

    # Fila 1: encabezados (siempre texto).
    fila_celdas = []
    for c, nombre_col in enumerate(columnas):
        ref = f"{_col_letter(c)}1"
        fila_celdas.append(_cell_xml(ref, str(nombre_col)))
    partes.append(f'<row r="1">{"".join(fila_celdas)}</row>')

    for r, fila in enumerate(df.itertuples(index=False, name=None), start=2):
        celdas = []
        for c, valor in enumerate(fila):
            if valor is None or (not isinstance(valor, (str, bool)) and pd.isna(valor)):
                continue
            ref = f"{_col_letter(c)}{r}"
            celdas.append(_cell_xml(ref, valor))
        partes.append(f'<row r="{r}">{"".join(celdas)}</row>')

    partes.append("</sheetData></worksheet>")
    return "".join(partes)


def write_workbook(path: str | Path, sheets: dict[str, pd.DataFrame], sheet_order: list[str]) -> None:
    """Escribe `sheets` (nombre -> DataFrame) como un .xlsx válido en `path`,
    en el orden exacto de `sheet_order`. R11 (ninguna celda de texto se
    guarda como fórmula) se cumple SIEMPRE: todo texto se escribe con
    `t="inlineStr"`, que nunca se evalúa como fórmula sin importar su
    contenido — a diferencia de openpyxl, aquí no hace falta distinguir
    casos: un `<c t="inlineStr">` jamás es `t="f"`.
    """
    nombres = [n for n in sheet_order if n in sheets]

    content_types = [_CONTENT_TYPES_HEADER]
    workbook_sheets = []
    workbook_rels = [
        '<Relationship Id="rIdStyles" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    ]
    sheet_files: dict[str, str] = {}

    for i, nombre in enumerate(nombres, start=1):
        rid = f"rId{i}"
        titulo_seguro = nombre[:31]
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        workbook_sheets.append(f'<sheet name={quoteattr(titulo_seguro)} sheetId="{i}" r:id="{rid}"/>')
        workbook_rels.append(
            f'<Relationship Id="{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
        sheet_files[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheets[nombre])

    content_types.append("</Types>")

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheets)}</sheets>'
        "</workbook>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(workbook_rels)}'
        "</Relationships>"
    )

    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", _STYLES_XML)
        for nombre_archivo, contenido in sheet_files.items():
            zf.writestr(nombre_archivo, contenido)
