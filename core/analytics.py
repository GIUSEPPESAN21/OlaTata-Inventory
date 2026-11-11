"""Análisis de ventas: KPIs y reportes de Hoy / Semana / Mes (§7 del encargo).

CONTRATO CONGELADO (ver docs/CONTRATOS.md): este módulo NUNCA modifica
`core/schema.py`, `core/money.py`, `core/timeutil.py`, `core/storage.py`
ni `core/permissions.py` — solo los importa.

Reglas de negocio implementadas aquí (textuales del encargo, §7):

- Ventas netas = Σ total_linea de ventas completadas del periodo − valor
  de devoluciones hechas en el periodo (excluye envío).
- Tickets = nº de ventas completadas. Unidades = Σ cantidad − unidades
  devueltas. Ticket promedio = Ventas netas / Tickets.
- Costo de lo vendido = Σ cantidad×costo_unitario (foto) − costo de lo
  devuelto que volvió a stock. Ganancia = Ventas netas − Costo de lo
  vendido. Margen % = Ganancia / Ventas netas (R1: "—" si denominador 0).
- El envío cobrado (`ventas.envio_cobrado`) NUNCA entra en "ventas
  netas" ni en "ganancia" (R7): como vive en la cabecera de la venta y
  no en `venta_items`, basta con nunca sumarlo ahí.
- Una venta "anulada" se EXCLUYE de todo KPI (R9).
- Una devolución resta en el día en que se HIZO (su propia
  `fecha_hora_utc`), nunca en el día de la venta original (R9).
- Rol sin "ver_analisis_completo" (vendedor): el resultado NO incluye
  las claves de costo/ganancia/margen (no se ocultan en la UI, se
  omiten del dict — §10, revalidación en core/).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from core import schema
from core.money import format_cop, format_percent, round_half_up_pesos
from core.permissions import PermisoDenegadoError, tiene_capacidad
from core.timeutil import BOGOTA, UTC, month_bounds_utc, week_bounds_utc


def _requerir_analisis_basico(rol: str) -> None:
    """"ver_analisis_completo" (admin) IMPLICA poder ver el análisis
    básico — el admin no tiene listada "ver_analisis_basico" en
    `core.permissions.CAPABILITIES` porque ya tiene el superconjunto
    "ver_analisis_completo". `requerir()` exige coincidencia EXACTA de
    capacidad, así que revalidamos aquí la unión de ambas en vez de
    editar el contrato congelado de permisos sin pedirlo primero."""
    if tiene_capacidad(rol, "ver_analisis_basico") or tiene_capacidad(rol, "ver_analisis_completo"):
        return
    raise PermisoDenegadoError(rol, "ver_analisis_basico")

__all__ = [
    "dia_bounds_utc",
    "kpis_hoy",
    "kpis_semana",
    "kpis_mes",
    "kpis_mes_cerrado",
    "oraculo_periodo",
    "valor_inventario",
    "productos_bajo_minimo_y_agotados",
    "productos_sin_ventas_en_dias",
]

_HOJAS_PERIODO = (
    schema.VENTAS,
    schema.VENTA_ITEMS,
    schema.PAGOS,
    schema.DEVOLUCIONES,
    schema.DEVOLUCION_ITEMS,
)

_COLOR_PRIMARIO = "#C2185B"
_COLOR_DORADO = "#C09860"
PALETA_MARCA = ["#C2185B", "#C09860", "#FC7DA9", "#7A5A1F", "#2B1B22"]


# ============================================================ utilidades
def dia_bounds_utc(fecha_local: date) -> tuple[datetime, datetime]:
    """Límites [inicio, fin) del día calendario de Bogotá, en UTC.

    `core.timeutil` (contrato congelado) expone `month_bounds_utc` y
    `week_bounds_utc`, pero NO un `day_bounds_utc`. En vez de reinventar
    el corte de fecha (R2: nunca `datetime.now(timezone.utc).date()`,
    ese es exactamente el defecto del repo de referencia), replicamos
    aquí la MISMA técnica que usa `core.timeutil` internamente: medianoche
    de Bogotá (con la zona pública `BOGOTA`) convertida a `UTC` (también
    pública). Se pide en el informe final exponer esto como
    `day_bounds_utc` en `core.timeutil` para no duplicar la técnica.
    """
    inicio_local = datetime(fecha_local.year, fecha_local.month, fecha_local.day, 0, 0, 0, tzinfo=BOGOTA)
    fin_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(UTC), fin_local.astimezone(UTC)


def _mes_clave(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _archive_path(mes_clave: str) -> str:
    return f"cierres/{mes_clave}.xlsx"


def _mes_anterior(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _dias_del_mes(year: int, month: int) -> int:
    inicio, fin = month_bounds_utc(year, month)
    primero_local = inicio.astimezone(BOGOTA).date()
    ultimo_local = (fin - timedelta(seconds=1)).astimezone(BOGOTA).date()
    return (ultimo_local - primero_local).days + 1


def _entero(serie: pd.Series) -> pd.Series:
    if serie.empty:
        return serie.astype("int64")
    return pd.to_numeric(serie, errors="coerce").fillna(0).astype("int64")


def _suma_entera(serie: pd.Series) -> int:
    return int(_entero(serie).sum())


def _col_fecha_utc(df: pd.DataFrame, columna: str = "fecha_hora_utc") -> pd.Series:
    if df.empty:
        return pd.Series([], dtype="datetime64[ns, UTC]")
    return pd.to_datetime(df[columna], utc=True, errors="coerce")


def _filtrar_rango(df: pd.DataFrame, inicio_utc: datetime, fin_utc: datetime, columna: str = "fecha_hora_utc") -> pd.DataFrame:
    if df.empty:
        return df
    ts = _col_fecha_utc(df, columna)
    mascara = (ts >= pd.Timestamp(inicio_utc)) & (ts < pd.Timestamp(fin_utc))
    return df[mascara].reset_index(drop=True)


def _leer_hoja_archivo(storage: Any, mes_clave: str, nombre_hoja: str) -> pd.DataFrame | None:
    contenido = storage.archive_get_bytes(_archive_path(mes_clave))
    if not contenido:
        return None
    libro = pd.read_excel(io.BytesIO(contenido), sheet_name=None, dtype=object)
    df = libro.get(nombre_hoja)
    if df is None:
        return None
    columnas = schema.columnas(nombre_hoja)
    df = df.copy()
    for col in columnas:
        if col not in df.columns:
            df[col] = pd.NA
    return df[columnas].reset_index(drop=True)


def _meses_en_rango(inicio_utc: datetime, fin_utc: datetime) -> list[str]:
    """Meses calendario de Bogotá (AAAA-MM) tocados por [inicio_utc, fin_utc)."""
    cursor = inicio_utc.astimezone(BOGOTA).date()
    fin_local_incl = (fin_utc - timedelta(seconds=1)).astimezone(BOGOTA).date()
    meses: list[str] = []
    while True:
        clave = _mes_clave(cursor)
        if clave not in meses:
            meses.append(clave)
        if cursor >= fin_local_incl:
            break
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return meses


def _combinar_hoja(storage: Any, nombre_hoja: str, meses: list[str]) -> pd.DataFrame:
    """Hoja en vivo + hojas archivadas (meses anteriores, §8) ya cerradas.

    No hay solapamiento esperado: el cierre de mes archiva Y VACÍA la
    base viva (regla del proyecto), así que un mes archivado nunca
    también está en `storage.read_sheet(...)`. Por seguridad igual
    deduplicamos por `id`.
    """
    base = storage.read_sheet(nombre_hoja)
    partes = [base]
    for mes in meses:
        extra = _leer_hoja_archivo(storage, mes, nombre_hoja)
        if extra is not None and not extra.empty:
            partes.append(extra)
    combinado = pd.concat(partes, ignore_index=True) if partes else base
    if "id" in combinado.columns and not combinado.empty:
        combinado = combinado.drop_duplicates(subset=["id"], keep="first").reset_index(drop=True)
    return combinado


def _cargar_periodo(storage: Any, inicio_utc: datetime, fin_utc: datetime) -> dict[str, pd.DataFrame]:
    meses = _meses_en_rango(inicio_utc, fin_utc)
    return {hoja: _combinar_hoja(storage, hoja, meses) for hoja in _HOJAS_PERIODO}


# ================================================================ núcleo
@dataclass
class _DatosPeriodo:
    ventas: pd.DataFrame
    venta_items: pd.DataFrame
    pagos: pd.DataFrame
    devoluciones: pd.DataFrame
    devolucion_items: pd.DataFrame


def _filtrar_periodo(
    hojas: dict[str, pd.DataFrame],
    inicio_utc: datetime,
    fin_utc: datetime,
    usuario_id: str | None = None,
) -> _DatosPeriodo:
    ventas_todas = hojas[schema.VENTAS]
    ventas_completadas = ventas_todas[ventas_todas["estado"] == "completada"] if not ventas_todas.empty else ventas_todas
    ventas_periodo = _filtrar_rango(ventas_completadas, inicio_utc, fin_utc)
    if usuario_id is not None and not ventas_periodo.empty:
        ventas_periodo = ventas_periodo[ventas_periodo["vendedor_id"] == usuario_id].reset_index(drop=True)

    venta_items = hojas[schema.VENTA_ITEMS]
    if venta_items.empty or ventas_periodo.empty:
        venta_items_periodo = venta_items.iloc[0:0]
    else:
        ids_periodo = set(ventas_periodo["id"])
        venta_items_periodo = venta_items[venta_items["venta_id"].isin(ids_periodo)].reset_index(drop=True)

    pagos_periodo = _filtrar_rango(hojas[schema.PAGOS], inicio_utc, fin_utc)
    if usuario_id is not None and not pagos_periodo.empty:
        ids_vendedor = set(ventas_todas[ventas_todas["vendedor_id"] == usuario_id]["id"]) if not ventas_todas.empty else set()
        pagos_periodo = pagos_periodo[pagos_periodo["venta_id"].isin(ids_vendedor)].reset_index(drop=True)

    devoluciones_periodo = _filtrar_rango(hojas[schema.DEVOLUCIONES], inicio_utc, fin_utc)
    devolucion_items = hojas[schema.DEVOLUCION_ITEMS]
    if devolucion_items.empty or devoluciones_periodo.empty:
        devolucion_items_periodo = devolucion_items.iloc[0:0]
    else:
        ids_dev = set(devoluciones_periodo["id"])
        devolucion_items_periodo = devolucion_items[devolucion_items["devolucion_id"].isin(ids_dev)].reset_index(drop=True)

    return _DatosPeriodo(
        ventas=ventas_periodo,
        venta_items=venta_items_periodo,
        pagos=pagos_periodo,
        devoluciones=devoluciones_periodo,
        devolucion_items=devolucion_items_periodo,
    )


def _resumen_numeros(datos: _DatosPeriodo, rol: str) -> dict[str, Any]:
    """Las fórmulas EXACTAS de §7. Devuelve solo números (sin desgloses)."""
    unidades_vendidas = _suma_entera(datos.venta_items["cantidad"]) if not datos.venta_items.empty else 0
    unidades_devueltas = _suma_entera(datos.devolucion_items["cantidad"]) if not datos.devolucion_items.empty else 0
    unidades = unidades_vendidas - unidades_devueltas

    ventas_brutas = _suma_entera(datos.venta_items["total_linea"]) if not datos.venta_items.empty else 0

    if datos.devolucion_items.empty:
        valor_devuelto = 0
    else:
        valor_devuelto = _suma_entera(_entero(datos.devolucion_items["cantidad"]) * _entero(datos.devolucion_items["precio_unitario"]))

    ventas_netas = ventas_brutas - valor_devuelto
    tickets = int(len(datos.ventas))
    ticket_promedio = round_half_up_pesos(Decimal(ventas_netas) / Decimal(tickets)) if tickets > 0 else None

    descuentos_otorgados = _suma_entera(datos.ventas["descuento_total"]) if not datos.ventas.empty else 0
    envios_cobrados = _suma_entera(datos.ventas["envio_cobrado"]) if not datos.ventas.empty else 0

    resultado: dict[str, Any] = {
        "ventas_netas": ventas_netas,
        "tickets": tickets,
        "unidades": unidades,
        "unidades_vendidas": unidades_vendidas,
        "ticket_promedio": ticket_promedio,
        "ticket_promedio_fmt": format_cop(ticket_promedio) if ticket_promedio is not None else "—",
        "descuentos_otorgados": descuentos_otorgados,
        "envios_cobrados": envios_cobrados,
        "devoluciones_valor": valor_devuelto,
        "devoluciones_unidades": unidades_devueltas,
    }

    if tiene_capacidad(rol, "ver_analisis_completo"):
        if datos.venta_items.empty:
            costo_vendido_bruto = 0
        else:
            costo_vendido_bruto = _suma_entera(_entero(datos.venta_items["cantidad"]) * _entero(datos.venta_items["costo_unitario"]))

        if datos.devolucion_items.empty:
            costo_devuelto_a_stock = 0
        else:
            devueltos_a_stock = datos.devolucion_items[datos.devolucion_items["destino"] == "stock"]
            costo_devuelto_a_stock = (
                _suma_entera(_entero(devueltos_a_stock["cantidad"]) * _entero(devueltos_a_stock["costo_unitario"]))
                if not devueltos_a_stock.empty
                else 0
            )

        costo_vendido = costo_vendido_bruto - costo_devuelto_a_stock
        ganancia = ventas_netas - costo_vendido

        resultado["costo_vendido"] = costo_vendido
        resultado["ganancia"] = ganancia
        resultado["margen_pct"] = format_percent(ganancia, ventas_netas)

    return resultado


def oraculo_periodo(storage: Any, inicio_utc: datetime, fin_utc: datetime) -> dict[str, Any]:
    """Recalcula TODO desde cero, con bucles explícitos (sin vectorizar,
    sin cachés intermedias), fila por fila sobre las hojas crudas — para
    comparar en pruebas contra la implementación vectorizada de arriba.
    Siempre calcula costo/ganancia (es una herramienta de verificación,
    no una vista con permisos).
    """
    hojas = _cargar_periodo(storage, inicio_utc, fin_utc)
    ventas = hojas[schema.VENTA_ITEMS]
    ventas_cab = hojas[schema.VENTAS]
    devoluciones_cab = hojas[schema.DEVOLUCIONES]
    devolucion_items = hojas[schema.DEVOLUCION_ITEMS]

    ids_completadas_periodo: set[Any] = set()
    for _, fila in ventas_cab.iterrows():
        if fila.get("estado") != "completada":
            continue
        ts = pd.to_datetime(fila.get("fecha_hora_utc"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        if inicio_utc <= ts.to_pydatetime() < fin_utc:
            ids_completadas_periodo.add(fila["id"])

    ventas_netas_bruto = 0
    costo_vendido_bruto = 0
    unidades_vendidas = 0
    for _, fila in ventas.iterrows():
        if fila.get("venta_id") not in ids_completadas_periodo:
            continue
        cantidad = int(fila.get("cantidad") or 0)
        total_linea = int(fila.get("total_linea") or 0)
        costo_unitario = int(fila.get("costo_unitario") or 0)
        ventas_netas_bruto += total_linea
        costo_vendido_bruto += cantidad * costo_unitario
        unidades_vendidas += cantidad

    ids_devolucion_periodo: set[Any] = set()
    for _, fila in devoluciones_cab.iterrows():
        ts = pd.to_datetime(fila.get("fecha_hora_utc"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        if inicio_utc <= ts.to_pydatetime() < fin_utc:
            ids_devolucion_periodo.add(fila["id"])

    valor_devuelto = 0
    costo_devuelto_a_stock = 0
    unidades_devueltas = 0
    for _, fila in devolucion_items.iterrows():
        if fila.get("devolucion_id") not in ids_devolucion_periodo:
            continue
        cantidad = int(fila.get("cantidad") or 0)
        precio_unitario = int(fila.get("precio_unitario") or 0)
        costo_unitario = int(fila.get("costo_unitario") or 0)
        valor_devuelto += cantidad * precio_unitario
        unidades_devueltas += cantidad
        if fila.get("destino") == "stock":
            costo_devuelto_a_stock += cantidad * costo_unitario

    ventas_netas = ventas_netas_bruto - valor_devuelto
    costo_vendido = costo_vendido_bruto - costo_devuelto_a_stock
    ganancia = ventas_netas - costo_vendido
    tickets = len(ids_completadas_periodo)

    return {
        "ventas_netas": ventas_netas,
        "tickets": tickets,
        "unidades": unidades_vendidas - unidades_devueltas,
        "costo_vendido": costo_vendido,
        "ganancia": ganancia,
        "margen_pct": format_percent(ganancia, ventas_netas),
        "devoluciones_valor": valor_devuelto,
        "devoluciones_unidades": unidades_devueltas,
    }


# ========================================================== desgloses
def _por_metodo_pago(datos: _DatosPeriodo) -> list[dict[str, Any]]:
    if datos.pagos.empty:
        filas = []
    else:
        agg = datos.pagos.assign(monto=_entero(datos.pagos["monto"])).groupby("metodo", as_index=False).agg(
            total=("monto", "sum"), nro_pagos=("monto", "count")
        )
        filas = agg.to_dict("records")
    reembolsos_cambio = 0
    total_pagos_no_cambio = sum(f["total"] for f in filas if f["metodo"] != "cambio")
    if not datos.devoluciones.empty:
        no_cambio = datos.devoluciones[datos.devoluciones["reembolso_metodo"] != "cambio"]
        reembolsos_cambio = _suma_entera(no_cambio["reembolso_monto"]) if not no_cambio.empty else 0
    flujo_caja = total_pagos_no_cambio - reembolsos_cambio
    return {"por_metodo": filas, "flujo_caja": flujo_caja}


def _por_canal(datos: _DatosPeriodo, ventas_todas: pd.DataFrame) -> list[dict[str, Any]]:
    if datos.venta_items.empty or datos.ventas.empty:
        ventas_por_canal: dict[str, int] = {}
    else:
        mapa_canal = dict(zip(datos.ventas["id"], datos.ventas["canal"]))
        items = datos.venta_items.assign(
            canal=datos.venta_items["venta_id"].map(mapa_canal),
            total_linea=_entero(datos.venta_items["total_linea"]),
        )
        ventas_por_canal = items.groupby("canal")["total_linea"].sum().astype(int).to_dict()

    devueltos_por_canal: dict[str, int] = {}
    if not datos.devolucion_items.empty and not datos.devoluciones.empty and not ventas_todas.empty:
        mapa_numero_canal = dict(zip(ventas_todas["numero"], ventas_todas["canal"]))
        mapa_dev_numero = dict(zip(datos.devoluciones["id"], datos.devoluciones["venta_numero"]))
        tmp = datos.devolucion_items.copy()
        tmp["numero"] = tmp["devolucion_id"].map(mapa_dev_numero)
        tmp["canal"] = tmp["numero"].map(mapa_numero_canal)
        tmp["valor"] = _entero(tmp["cantidad"]) * _entero(tmp["precio_unitario"])
        devueltos_por_canal = tmp.groupby("canal")["valor"].sum().astype(int).to_dict()

    canales = set(ventas_por_canal) | set(devueltos_por_canal)
    return [
        {
            "canal": canal,
            "ventas_netas": int(ventas_por_canal.get(canal, 0)) - int(devueltos_por_canal.get(canal, 0)),
        }
        for canal in sorted(c for c in canales if c is not None and not pd.isna(c))
    ]


def _por_categoria(datos: _DatosPeriodo, productos: pd.DataFrame) -> list[dict[str, Any]]:
    if productos.empty:
        mapa_categoria: dict[Any, Any] = {}
    else:
        mapa_categoria = dict(zip(productos["id"], productos["categoria"]))

    if datos.venta_items.empty:
        ventas_por_categoria: dict[Any, int] = {}
    else:
        items = datos.venta_items.assign(
            categoria=datos.venta_items["producto_id"].map(mapa_categoria),
            total_linea=_entero(datos.venta_items["total_linea"]),
        )
        ventas_por_categoria = items.groupby("categoria")["total_linea"].sum().astype(int).to_dict()

    if datos.devolucion_items.empty:
        devueltos_por_categoria: dict[Any, int] = {}
    else:
        items = datos.devolucion_items.assign(
            categoria=datos.devolucion_items["producto_id"].map(mapa_categoria),
            valor=_entero(datos.devolucion_items["cantidad"]) * _entero(datos.devolucion_items["precio_unitario"]),
        )
        devueltos_por_categoria = items.groupby("categoria")["valor"].sum().astype(int).to_dict()

    categorias = set(ventas_por_categoria) | set(devueltos_por_categoria)
    return [
        {
            "categoria": cat,
            "ventas_netas": int(ventas_por_categoria.get(cat, 0)) - int(devueltos_por_categoria.get(cat, 0)),
        }
        for cat in sorted(c for c in categorias if c is not None and not pd.isna(c))
    ]


def _top_productos(datos: _DatosPeriodo, rol: str, n: int = 10) -> dict[str, list[dict[str, Any]]]:
    if datos.venta_items.empty:
        return {"por_unidades": [], "por_ganancia": []}

    items = datos.venta_items.copy()
    items["cantidad"] = _entero(items["cantidad"])
    items["total_linea"] = _entero(items["total_linea"])

    por_unidades = (
        items.groupby(["producto_id", "nombre_snapshot"], as_index=False)["cantidad"]
        .sum()
        .sort_values("cantidad", ascending=False)
        .head(n)
        .to_dict("records")
    )

    resultado = {"por_unidades": por_unidades}

    if tiene_capacidad(rol, "ver_analisis_completo"):
        items["costo_unitario"] = _entero(items["costo_unitario"])
        items["ganancia_linea"] = items["total_linea"] - items["cantidad"] * items["costo_unitario"]

        # Devoluciones que afectan la ganancia neta por producto.
        ganancia_devuelta = pd.Series(dtype="int64")
        if not datos.devolucion_items.empty:
            dev = datos.devolucion_items.copy()
            dev["cantidad"] = _entero(dev["cantidad"])
            dev["precio_unitario"] = _entero(dev["precio_unitario"])
            dev["costo_unitario"] = _entero(dev["costo_unitario"])
            dev["recupera_costo"] = (dev["destino"] == "stock").astype(int)
            dev["impacto"] = -(dev["cantidad"] * dev["precio_unitario"]) + dev["recupera_costo"] * (dev["cantidad"] * dev["costo_unitario"])
            ganancia_devuelta = dev.groupby("producto_id")["impacto"].sum()

        ganancia_por_producto = items.groupby("producto_id")["ganancia_linea"].sum()
        if not ganancia_devuelta.empty:
            ganancia_por_producto = ganancia_por_producto.add(ganancia_devuelta, fill_value=0)
        nombres = dict(zip(items["producto_id"], items["nombre_snapshot"]))
        por_ganancia = (
            ganancia_por_producto.reset_index(name="ganancia")
            .assign(nombre_snapshot=lambda d: d["producto_id"].map(nombres))
            .sort_values("ganancia", ascending=False)
            .head(n)
            .to_dict("records")
        )
        resultado["por_ganancia"] = por_ganancia

    return resultado


def _lista_ventas(datos: _DatosPeriodo) -> list[dict[str, Any]]:
    if datos.ventas.empty:
        return []
    cols = [c for c in ["id", "numero", "fecha_hora_utc", "canal", "cliente_nombre", "total", "vendedor_nombre"] if c in datos.ventas.columns]
    df = datos.ventas[cols].copy()
    df = df.sort_values("fecha_hora_utc")
    return df.to_dict("records")


# =========================================================== inventario
def valor_inventario(storage: Any) -> dict[str, int]:
    """Valor del inventario actual (foto de AHORA, no periodizado): al
    costo y al precio de venta, Σ stock.cantidad × producto.costo|precio."""
    stock = storage.read_sheet(schema.STOCK)
    productos = storage.read_sheet(schema.PRODUCTOS)
    if stock.empty or productos.empty:
        return {"al_costo": 0, "al_precio": 0}

    por_producto = stock.assign(cantidad=_entero(stock["cantidad"])).groupby("producto_id")["cantidad"].sum()
    productos_idx = productos.set_index("id")
    costo = _entero(productos_idx["costo"]) if "costo" in productos_idx.columns else pd.Series(dtype="int64")
    precio = _entero(productos_idx["precio"]) if "precio" in productos_idx.columns else pd.Series(dtype="int64")

    al_costo = 0
    al_precio = 0
    for producto_id, cantidad in por_producto.items():
        if producto_id in costo.index:
            al_costo += int(cantidad) * int(costo.loc[producto_id])
        if producto_id in precio.index:
            al_precio += int(cantidad) * int(precio.loc[producto_id])
    return {"al_costo": al_costo, "al_precio": al_precio}


def productos_bajo_minimo_y_agotados(storage: Any) -> dict[str, int]:
    """Nº de productos bajo mínimo (stock>0 y <= stock_minimo) y agotados
    (stock==0), sobre el estado ACTUAL de `stock`/`productos`."""
    stock = storage.read_sheet(schema.STOCK)
    productos = storage.read_sheet(schema.PRODUCTOS)
    if productos.empty:
        return {"bajo_minimo": 0, "agotados": 0}

    if stock.empty:
        totales = pd.Series(dtype="int64")
    else:
        totales = stock.assign(cantidad=_entero(stock["cantidad"])).groupby("producto_id")["cantidad"].sum()

    bajo_minimo = 0
    agotados = 0
    minimos = _entero(productos.set_index("id")["stock_minimo"]) if "stock_minimo" in productos.columns else pd.Series(dtype="int64")
    for producto_id in productos["id"]:
        cantidad = int(totales.get(producto_id, 0))
        minimo = int(minimos.get(producto_id, 0))
        if cantidad == 0:
            agotados += 1
        elif cantidad <= minimo:
            bajo_minimo += 1
    return {"bajo_minimo": bajo_minimo, "agotados": agotados}


def productos_sin_ventas_en_dias(storage: Any, fecha_local: date, dias: int = 30) -> list[dict[str, Any]]:
    """Productos activos con stock > 0 que NO se vendieron en los últimos
    `dias` días calendario (ventana corrida, puede cruzar de mes — se
    apoya en `_cargar_periodo` para leer el archivo si hace falta)."""
    fin_utc = dia_bounds_utc(fecha_local)[1]
    inicio_utc = dia_bounds_utc(fecha_local - timedelta(days=dias))[0]
    hojas = _cargar_periodo(storage, inicio_utc, fin_utc)
    ventas_cab = hojas[schema.VENTAS]
    venta_items = hojas[schema.VENTA_ITEMS]

    ids_completadas = set()
    if not ventas_cab.empty:
        completadas = ventas_cab[ventas_cab["estado"] == "completada"]
        completadas = _filtrar_rango(completadas, inicio_utc, fin_utc)
        ids_completadas = set(completadas["id"])

    productos_vendidos: set[Any] = set()
    if not venta_items.empty and ids_completadas:
        vendidos = venta_items[venta_items["venta_id"].isin(ids_completadas)]
        productos_vendidos = set(vendidos["producto_id"])

    productos = storage.read_sheet(schema.PRODUCTOS)
    stock = storage.read_sheet(schema.STOCK)
    totales = stock.assign(cantidad=_entero(stock["cantidad"])).groupby("producto_id")["cantidad"].sum() if not stock.empty else pd.Series(dtype="int64")

    resultado = []
    for _, fila in productos.iterrows():
        producto_id = fila["id"]
        if fila.get("activo") is False:
            continue
        cantidad = int(totales.get(producto_id, 0))
        if cantidad <= 0:
            continue
        if producto_id in productos_vendidos:
            continue
        resultado.append({"producto_id": producto_id, "nombre": fila.get("nombre"), "stock": cantidad})
    return resultado


# =============================================================== KPIs
def _resumen_rango(
    storage: Any,
    inicio_utc: datetime,
    fin_utc: datetime,
    rol: str,
    usuario_id: str | None = None,
) -> tuple[dict[str, Any], _DatosPeriodo, pd.DataFrame]:
    hojas = _cargar_periodo(storage, inicio_utc, fin_utc)
    datos = _filtrar_periodo(hojas, inicio_utc, fin_utc, usuario_id=usuario_id)
    numeros = _resumen_numeros(datos, rol)
    return numeros, datos, hojas[schema.VENTAS]


def _comparar(actual: int, anterior: int) -> dict[str, Any]:
    diferencia = actual - anterior
    variacion_pct = format_percent(diferencia, anterior) if anterior else "—"
    return {"actual": actual, "anterior": anterior, "diferencia": diferencia, "variacion_pct": variacion_pct}


def kpis_hoy(storage: Any, fecha_local: date, rol: str, usuario_id: str | None = None) -> dict[str, Any]:
    """KPIs + desgloses del día (§7 "HOY"). Revalida "ver_analisis_basico"."""
    _requerir_analisis_basico(rol)
    inicio_utc, fin_utc = dia_bounds_utc(fecha_local)
    numeros, datos, ventas_todas = _resumen_rango(storage, inicio_utc, fin_utc, rol, usuario_id)

    resultado: dict[str, Any] = {"fecha_local": fecha_local.isoformat(), **numeros}

    # Ventas por hora (bruto de línea, hora local de Bogotá de la venta).
    por_hora: dict[int, int] = {}
    if not datos.venta_items.empty and not datos.ventas.empty:
        mapa_hora = {}
        for _, fila in datos.ventas.iterrows():
            ts = pd.to_datetime(fila["fecha_hora_utc"], utc=True)
            mapa_hora[fila["id"]] = ts.tz_convert(BOGOTA).hour
        items = datos.venta_items.assign(
            hora=datos.venta_items["venta_id"].map(mapa_hora),
            total_linea=_entero(datos.venta_items["total_linea"]),
        )
        por_hora = items.groupby("hora")["total_linea"].sum().astype(int).to_dict()
    resultado["ventas_por_hora"] = [{"hora": h, "total": por_hora.get(h, 0)} for h in range(24)]

    metodo = _por_metodo_pago(datos)
    resultado["por_metodo_pago"] = metodo["por_metodo"]
    resultado["flujo_caja"] = metodo["flujo_caja"]
    resultado["por_canal"] = _por_canal(datos, ventas_todas)

    productos = storage.read_sheet(schema.PRODUCTOS)
    resultado["por_categoria"] = _por_categoria(datos, productos)
    resultado.update(_top_productos(datos, rol))
    resultado["ventas_del_dia"] = _lista_ventas(datos)

    # Comparativos.
    ayer_numeros, _, _ = _resumen_rango(storage, *dia_bounds_utc(fecha_local - timedelta(days=1)), rol, usuario_id)
    semana_pasada_numeros, _, _ = _resumen_rango(storage, *dia_bounds_utc(fecha_local - timedelta(days=7)), rol, usuario_id)
    resultado["comparativo_ayer"] = _comparar(numeros["ventas_netas"], ayer_numeros["ventas_netas"])
    resultado["comparativo_semana_pasada"] = _comparar(numeros["ventas_netas"], semana_pasada_numeros["ventas_netas"])

    return resultado


def kpis_semana(storage: Any, fecha_local: date, rol: str, usuario_id: str | None = None) -> dict[str, Any]:
    """KPIs + desgloses de la semana (lunes de Bogotá → hoy, §7 "SEMANA")."""
    _requerir_analisis_basico(rol)
    inicio_semana, _ = week_bounds_utc(fecha_local)
    fin_utc = dia_bounds_utc(fecha_local)[1]
    numeros, datos, ventas_todas = _resumen_rango(storage, inicio_semana, fin_utc, rol, usuario_id)

    resultado: dict[str, Any] = {"inicio_semana": inicio_semana.astimezone(BOGOTA).date().isoformat(), **numeros}

    lunes_local = inicio_semana.astimezone(BOGOTA).date()
    dias_transcurridos = (fecha_local - lunes_local).days + 1
    barras = []
    for offset in range(dias_transcurridos):
        dia = lunes_local + timedelta(days=offset)
        dia_num, _, _ = _resumen_rango(storage, *dia_bounds_utc(dia), rol, usuario_id)
        barras.append({"fecha": dia.isoformat(), "ventas_netas": dia_num["ventas_netas"]})
    resultado["barras_por_dia"] = barras

    resultado.update(_top_productos(datos, rol))

    lunes_pasado = lunes_local - timedelta(days=7)
    inicio_semana_pasada = dia_bounds_utc(lunes_pasado)[0]
    fin_semana_pasada = dia_bounds_utc(lunes_pasado + timedelta(days=dias_transcurridos - 1))[1]
    numeros_semana_pasada, _, _ = _resumen_rango(storage, inicio_semana_pasada, fin_semana_pasada, rol, usuario_id)
    resultado["comparativo_semana_anterior"] = _comparar(numeros["ventas_netas"], numeros_semana_pasada["ventas_netas"])

    return resultado


def kpis_mes(storage: Any, fecha_local: date, rol: str, usuario_id: str | None = None) -> dict[str, Any]:
    """KPIs + desgloses del mes en curso (día 1 de Bogotá → hoy, §7 "MES")."""
    _requerir_analisis_basico(rol)
    inicio_mes, _ = month_bounds_utc(fecha_local.year, fecha_local.month)
    fin_utc = dia_bounds_utc(fecha_local)[1]
    numeros, datos, ventas_todas = _resumen_rango(storage, inicio_mes, fin_utc, rol, usuario_id)

    resultado: dict[str, Any] = {"mes": _mes_clave(fecha_local), **numeros}

    primero_local = inicio_mes.astimezone(BOGOTA).date()
    dias_transcurridos = (fecha_local - primero_local).days + 1
    barras = []
    for offset in range(dias_transcurridos):
        dia = primero_local + timedelta(days=offset)
        dia_num, _, _ = _resumen_rango(storage, *dia_bounds_utc(dia), rol, usuario_id)
        barras.append({"fecha": dia.isoformat(), "ventas_netas": dia_num["ventas_netas"]})
    resultado["barras_por_dia"] = barras

    productos = storage.read_sheet(schema.PRODUCTOS)
    resultado["por_categoria"] = _por_categoria(datos, productos)
    resultado["por_canal"] = _por_canal(datos, ventas_todas)
    resultado["por_metodo_pago"] = _por_metodo_pago(datos)["por_metodo"]
    resultado.update(_top_productos(datos, rol))
    resultado["stock_sin_ventas_30_dias"] = productos_sin_ventas_en_dias(storage, fecha_local, dias=30)

    year_ant, month_ant = _mes_anterior(fecha_local.year, fecha_local.month)
    inicio_mes_ant, _ = month_bounds_utc(year_ant, month_ant)
    primero_ant = inicio_mes_ant.astimezone(BOGOTA).date()
    dias_mes_ant = _dias_del_mes(year_ant, month_ant)
    dia_comparable = min(dias_transcurridos, dias_mes_ant)
    fin_mes_ant = dia_bounds_utc(primero_ant + timedelta(days=dia_comparable - 1))[1]
    numeros_mes_ant, _, _ = _resumen_rango(storage, inicio_mes_ant, fin_mes_ant, rol, usuario_id)
    resultado["comparativo_mes_anterior"] = _comparar(numeros["ventas_netas"], numeros_mes_ant["ventas_netas"])

    dias_totales_mes = _dias_del_mes(fecha_local.year, fecha_local.month)
    promedio_diario = Decimal(numeros["ventas_netas"]) / Decimal(dias_transcurridos) if dias_transcurridos else Decimal(0)
    resultado["proyeccion_cierre"] = {
        "valor": round_half_up_pesos(promedio_diario * Decimal(dias_totales_mes)),
        "etiqueta": "estimado",
    }

    resultado["valor_inventario"] = valor_inventario(storage)
    resultado["productos_bajo_minimo_y_agotados"] = productos_bajo_minimo_y_agotados(storage)

    return resultado


def kpis_mes_cerrado(storage: Any, year: int, month: int, rol: str) -> dict[str, Any]:
    """Mes YA CERRADO (§7 "MESES ANTERIORES"): lee `cierres/AAAA-MM.xlsx`
    completo (vía `storage.archive_get_bytes`), mes calendario completo."""
    _requerir_analisis_basico(rol)
    inicio_utc, fin_utc = month_bounds_utc(year, month)
    numeros, datos, ventas_todas = _resumen_rango(storage, inicio_utc, fin_utc, rol)
    resultado: dict[str, Any] = {"mes": f"{year:04d}-{month:02d}", **numeros}
    productos = storage.read_sheet(schema.PRODUCTOS)
    resultado["por_categoria"] = _por_categoria(datos, productos)
    resultado["por_canal"] = _por_canal(datos, ventas_todas)
    resultado["por_metodo_pago"] = _por_metodo_pago(datos)["por_metodo"]
    resultado.update(_top_productos(datos, rol))
    return resultado
