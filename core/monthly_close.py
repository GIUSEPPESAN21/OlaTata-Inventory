"""Cierre mensual (§8 del encargo): archiva y VACÍA las 7 hojas
transaccionales (`core.schema.HOJAS_TRANSACCIONALES_MENSUALES`) de un mes
YA TERMINADO, preservando el inventario (stock) mediante un movimiento
"apertura" por producto al abrir el mes siguiente (R4: el invariante
``stock = Σ movimientos`` debe seguir cumpliéndose DESPUÉS del cierre).

## Los 4 pasos (§8) y su estado intermedio

``cerrar_mes`` ejecuta, en secuencia, 4 funciones internas:

1. ``_paso1_construir_snapshot`` — SOLO LECTURA de la base viva (las 7
   hojas transaccionales filtradas por el mes M, más ``stock_cierre`` y
   ``resumen_mes``). No tiene efectos persistentes: si el proceso se
   corta aquí, la siguiente llamada simplemente lo reconstruye desde cero
   (la base viva todavía no cambió).
2. ``_paso2_publicar`` — sube ``cierres/AAAA-MM.xlsx`` y actualiza
   ``cierres/INDEX.json`` en OlaTata-Archive (vía
   ``storage.archive_put_bytes``). Ninguna de las dos escrituras necesita
   ser "la primera vez": el archivo se sobreescribe con el mismo
   contenido determinista si se reintenta, y
   ``archive.actualizar_index`` REEMPLAZA (nunca duplica) la entrada de
   ese mismo archivo. Al final deja un registro informativo en
   ``config["cierre::progreso"]``.
3. ``_paso3_verificar`` — vuelve a "descargar" lo recién publicado
   (``storage.archive_get_bytes``), recalcula SHA-256 y conteos de filas
   por hoja, y los compara contra el snapshot. Si algo no coincide, lanza
   ``CierreVerificacionError`` ANTES de tocar la base viva (los pasos 1-2
   solo escriben en Archive, nunca en la base viva).
4. ``_paso4_aplicar`` — la ÚNICA mutación de la base viva, dentro de UNA
   transacción (``storage.transaction()``): quita las filas del mes M de
   las 7 hojas, escribe los movimientos "apertura", actualiza
   ``config["ultimo_mes_cerrado"]`` y registra ``auditoria``. Por R6, si
   algo falla a mitad de esta transacción no queda NADA a medias (el
   ``except`` de ``Storage.transaction()``/``FakeStorage.transaction()``
   descarta todo cambio en memoria). Al salir con éxito,
   ``ultimo_mes_cerrado`` queda en ``year-month``: esa es la ÚNICA marca
   que ``cerrar_mes`` necesita para saber "este mes ya está cerrado" en
   la siguiente llamada.

### Por qué el estado se RECALCULA y no se "confía" en una bandera

Después de cada paso se guarda un registro informativo en
``config["cierre::progreso"]`` (JSON con year/month/paso/archivo/sha256),
útil para que un admin vea en qué quedó un cierre interrumpido. Pero la
decisión real de "¿por dónde reanudar?" NUNCA depende de esa bandera:
depende de releer el estado OBSERVABLE (¿``ultimo_mes_cerrado`` ya cubre
este mes?). Una bandera de "intención" escrita ANTES de que el efecto
ocurra puede mentir si el proceso muere entre escribir la bandera y
producir el efecto; el estado observable nunca miente. Por eso
``cerrar_mes`` simplemente reintenta los 4 pasos desde el principio en
cada llamada, y cada paso está diseñado para ser un no-op seguro (o
converger al mismo resultado) si ya se había completado antes — ese es
el sentido de "idempotente y a prueba de cortes" del §8.

## Fórmula de ``resumen_mes`` (KPIs simplificados)

A3 (análisis) todavía no existe en esta rama, así que este módulo calcula
una versión MÍNIMA y documentada (no es la lógica final de análisis, que
puede incluir costo promedio ponderado histórico, envíos, etc.):

- ``ventas_completadas`` / ``ventas_anuladas``: conteo de filas de
  ``ventas`` por ``estado``.
- ``ingresos_netos``: suma de ``ventas.total`` donde ``estado ==
  "completada"`` (las anuladas NO se descuentan porque nunca se suman).
- ``costo_vendido``: suma de ``venta_items.costo_unitario * cantidad``
  para los items de ventas COMPLETADAS (join por ``venta_id``).
- ``ganancia_bruta``: ``ingresos_netos - costo_vendido``.
- ``devoluciones_monto``: suma de ``devoluciones.reembolso_monto`` del
  mes (incluye devolución y cambio, sin descomponer por tipo).

## Supuesto sobre identidad del "usuario" del movimiento de apertura

``cerrar_mes`` recibe solo ``rol`` (como exige el encargo), no un
``usuario_id`` real. Los movimientos "apertura" se registran con
``usuario_id = "sistema:cierre_mensual"`` (no hay un vendedor/admin
individual detrás de una apertura de inventario). Si el equipo de
permisos/auditoría prefiere propagar el usuario real que ejecutó el
cierre, habría que ampliar la firma de ``cerrar_mes`` (pedido para el
informe final, no se hizo aquí porque cambiaría un contrato ya usado por
otros subagentes).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core import archive, schema
from core.excel_safe import excel_safe
from core.permissions import requerir
from core.timeutil import local_date, month_bounds_utc, now_utc, parse_iso_utc, to_iso_utc

__all__ = [
    "CierreMesInvalidoError",
    "CierreVerificacionError",
    "ResultadoCierre",
    "cerrar_mes",
]


class CierreMesInvalidoError(Exception):
    """El mes solicitado no se puede cerrar: es el mes en curso, es un mes
    futuro, o los parámetros (year, month) son inválidos."""


class CierreVerificacionError(Exception):
    """El cierre recién publicado en Archive no coincide con el snapshot
    construido desde la base viva (§8, paso 3). Se lanza ANTES del paso 4:
    la base viva queda intacta."""


@dataclass
class ResultadoCierre:
    """Resultado de `cerrar_mes`. Si `ya_estaba_cerrado` es True, los demás
    campos quedan en sus valores por defecto (no se repitió ningún
    trabajo, §8 "idempotente")."""

    year: int
    month: int
    ya_estaba_cerrado: bool
    archivo: str | None = None
    sha256: str | None = None
    filas_por_hoja: dict[str, int] = field(default_factory=dict)
    movimientos_apertura: int = 0
    mensaje: str = ""


# --------------------------------------------------------------- helpers


def _clave_mes(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _mes_actual_bogota() -> tuple[int, int]:
    hoy = local_date(now_utc())
    return hoy.year, hoy.month


def _to_int(valor: object) -> int:
    """Convierte un valor numérico que pudo volver de un round-trip de
    Excel como `float`/`str`/`None` a `int` (R1: dinero y cantidades
    siempre enteros)."""
    if valor is None:
        return 0
    try:
        if pd.isna(valor):
            return 0
    except (TypeError, ValueError):
        pass
    return int(float(valor))


def _parse_o_none(valor: object):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return parse_iso_utc(str(valor))
    except Exception:
        return None


def _ya_cerrado(storage, year: int, month: int) -> bool:
    valor = storage.get_config("ultimo_mes_cerrado")
    if not valor:
        return False
    try:
        y_str, m_str = valor.split("-")
        cerrado = (int(y_str), int(m_str))
    except (ValueError, AttributeError):
        return False
    return (year, month) <= cerrado


def _validar_mes_cerrable(year: int, month: int) -> None:
    if not (1 <= month <= 12):
        raise CierreMesInvalidoError(f"Mes inválido: {month}.")
    actual = _mes_actual_bogota()
    if (year, month) >= actual:
        raise CierreMesInvalidoError(
            f"No se puede cerrar {_clave_mes(year, month)}: es el mes en curso o uno futuro "
            f"(mes actual en Bogotá: {_clave_mes(*actual)}). Solo se cierran meses ya terminados."
        )


# ------------------------------------------------------------- paso 1


def _calcular_stock_cierre(storage, fin_utc) -> pd.DataFrame:
    """Para cada (producto_id, sede_id), toma el `stock_despues` del
    movimiento MÁS RECIENTE con `fecha_hora_utc < fin_utc` (es decir, el
    último movimiento del mes M o anterior). Se usa `movimientos` y NO la
    hoja `stock` directamente porque, si el cierre se hace tarde, `stock`
    ya puede incluir ventas de M+1 registradas antes del cierre — esas NO
    deben entrar en el `stock_cierre` de M (§8: "los movimientos de M+1
    registrados ANTES del cierre se conservan intactos")."""
    movimientos = storage.read_sheet(schema.MOVIMIENTOS)
    columnas_salida = ["producto_id", "nombre_producto", "sede_id", "cantidad", "costo", "valor"]
    if movimientos.empty:
        return pd.DataFrame(columns=columnas_salida)

    fechas = movimientos["fecha_hora_utc"].map(_parse_o_none)
    anteriores = movimientos[fechas.map(lambda f: f is not None and f < fin_utc)].copy()
    if anteriores.empty:
        return pd.DataFrame(columns=columnas_salida)

    anteriores["_fecha"] = anteriores["fecha_hora_utc"].map(_parse_o_none)
    anteriores = anteriores.sort_values("_fecha", kind="stable")
    ultimos = anteriores.groupby(["producto_id", "sede_id"], as_index=False, sort=False).tail(1)

    productos = storage.read_sheet(schema.PRODUCTOS).set_index("id")
    filas = []
    for _, fila in ultimos.iterrows():
        producto_id = fila["producto_id"]
        cantidad = _to_int(fila["stock_despues"])
        costo = 0
        nombre = ""
        if producto_id in productos.index:
            costo = _to_int(productos.loc[producto_id, "costo"])
            nombre = excel_safe(productos.loc[producto_id, "nombre"], field_name="nombre_producto")
        filas.append(
            {
                "producto_id": producto_id,
                "nombre_producto": nombre,
                "sede_id": fila["sede_id"],
                "cantidad": cantidad,
                "costo": costo,
                "valor": cantidad * costo,
            }
        )
    return pd.DataFrame(filas, columns=columnas_salida)


def _calcular_resumen_mes(
    ventas: pd.DataFrame, venta_items: pd.DataFrame, devoluciones: pd.DataFrame, year: int, month: int
) -> pd.DataFrame:
    """KPIs simplificados del mes. Ver fórmulas documentadas en el
    docstring del módulo."""
    completadas = ventas[ventas["estado"] == "completada"]
    anuladas = ventas[ventas["estado"] == "anulada"]

    ingresos_netos = int(completadas["total"].map(_to_int).sum()) if not completadas.empty else 0

    items_completados = venta_items[venta_items["venta_id"].isin(completadas["id"])]
    if items_completados.empty:
        costo_vendido = 0
    else:
        costo_vendido = int(
            (items_completados["costo_unitario"].map(_to_int) * items_completados["cantidad"].map(_to_int)).sum()
        )

    devoluciones_monto = int(devoluciones["reembolso_monto"].map(_to_int).sum()) if not devoluciones.empty else 0

    fila = {
        "year": year,
        "month": month,
        "ventas_completadas": int(len(completadas)),
        "ventas_anuladas": int(len(anuladas)),
        "ingresos_netos": ingresos_netos,
        "costo_vendido": costo_vendido,
        "ganancia_bruta": ingresos_netos - costo_vendido,
        "devoluciones_monto": devoluciones_monto,
    }
    return pd.DataFrame([fila])


def _paso1_construir_snapshot(storage, year: int, month: int) -> dict[str, pd.DataFrame]:
    """SOLO LECTURA. Construye el snapshot de las 7 hojas transaccionales
    del mes M + `stock_cierre` + `resumen_mes`. No escribe nada: es seguro
    volver a llamarla cuantas veces haga falta mientras la base viva no
    haya sido modificada todavía por el paso 4."""
    inicio, fin = month_bounds_utc(year, month)

    def _por_fecha_hora_utc(df: pd.DataFrame) -> pd.DataFrame:
        fechas = df["fecha_hora_utc"].map(_parse_o_none)
        en_rango = fechas.map(lambda f: f is not None and inicio <= f < fin)
        return df[en_rango].reset_index(drop=True)

    ventas = _por_fecha_hora_utc(storage.read_sheet(schema.VENTAS))
    pagos = _por_fecha_hora_utc(storage.read_sheet(schema.PAGOS))
    devoluciones = _por_fecha_hora_utc(storage.read_sheet(schema.DEVOLUCIONES))
    movimientos_mes = _por_fecha_hora_utc(storage.read_sheet(schema.MOVIMIENTOS))

    venta_ids = set(ventas["id"])
    venta_items_df = storage.read_sheet(schema.VENTA_ITEMS)
    venta_items = venta_items_df[venta_items_df["venta_id"].isin(venta_ids)].reset_index(drop=True)

    devolucion_ids = set(devoluciones["id"])
    devolucion_items_df = storage.read_sheet(schema.DEVOLUCION_ITEMS)
    devolucion_items = devolucion_items_df[devolucion_items_df["devolucion_id"].isin(devolucion_ids)].reset_index(
        drop=True
    )

    # CUADRE_CAJA no tiene `fecha_hora_utc` (solo `fecha_local`, ver
    # core/schema.py): se filtra por el mes calendario de Bogotá directo.
    inicio_local = date(year, month, 1)
    fin_local = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    def _fecha_local_en_rango(valor: object) -> bool:
        if valor is None or valor == "":
            return False
        try:
            if pd.isna(valor):
                return False
        except (TypeError, ValueError):
            pass
        try:
            d = date.fromisoformat(str(valor)[:10])
        except ValueError:
            return False
        return inicio_local <= d < fin_local

    cuadre_df = storage.read_sheet(schema.CUADRE_CAJA)
    cuadre_caja = cuadre_df[cuadre_df["fecha_local"].map(_fecha_local_en_rango)].reset_index(drop=True)

    stock_cierre = _calcular_stock_cierre(storage, fin)
    resumen_mes = _calcular_resumen_mes(ventas, venta_items, devoluciones, year, month)

    return {
        schema.VENTAS: ventas,
        schema.VENTA_ITEMS: venta_items,
        schema.PAGOS: pagos,
        schema.DEVOLUCIONES: devoluciones,
        schema.DEVOLUCION_ITEMS: devolucion_items,
        schema.MOVIMIENTOS: movimientos_mes,
        schema.CUADRE_CAJA: cuadre_caja,
        "stock_cierre": stock_cierre,
        "resumen_mes": resumen_mes,
    }


# ------------------------------------------------------------- paso 2


def _paso2_publicar(storage, year: int, month: int, snapshot: dict[str, pd.DataFrame]) -> tuple[str, str]:
    """Publica `cierres/AAAA-MM.xlsx` y actualiza `cierres/INDEX.json`.
    Idempotente: reintentar después de una caída sobreescribe el mismo
    archivo con el mismo contenido y REEMPLAZA (no duplica) la entrada del
    índice (ver `core.archive.actualizar_index`)."""
    nombre_archivo = f"{_clave_mes(year, month)}.xlsx"
    ruta_archivo = f"cierres/{nombre_archivo}"
    ruta_index = "cierres/INDEX.json"

    contenido = archive.construir_libro_cierre(snapshot)
    sha = archive.sha256_bytes(contenido)

    storage.archive_put_bytes(ruta_archivo, contenido, message=f"Cierre mensual {nombre_archivo}")

    index_actual = archive.leer_index(storage.archive_get_bytes(ruta_index))
    entrada = archive.construir_entrada_index(nombre_archivo, snapshot, sha)
    index_nuevo = archive.actualizar_index(index_actual, entrada)
    storage.archive_put_bytes(
        ruta_index, archive.serializar_index(index_nuevo), message=f"INDEX: agrega {nombre_archivo}"
    )

    with storage.transaction() as tx:
        tx.set_config(
            "cierre::progreso",
            json.dumps({"year": year, "month": month, "paso": "publicado", "archivo": nombre_archivo, "sha256": sha}),
        )
    return nombre_archivo, sha


# ------------------------------------------------------------- paso 3


def _paso3_verificar(
    storage, year: int, month: int, nombre_archivo: str, sha_esperado: str, snapshot: dict[str, pd.DataFrame]
) -> None:
    """Vuelve a "descargar" lo recién publicado y compara conteos de filas
    por hoja + SHA-256 contra el snapshot. Si algo no coincide, lanza
    `CierreVerificacionError` SIN tocar la base viva (§8, paso 3)."""
    ruta_archivo = f"cierres/{nombre_archivo}"
    contenido = storage.archive_get_bytes(ruta_archivo)
    if contenido is None:
        raise CierreVerificacionError(
            f"No se encontró '{ruta_archivo}' recién publicado en Archive; aborto el cierre de "
            f"{_clave_mes(year, month)} sin tocar la base viva."
        )

    sha_descargado = archive.sha256_bytes(contenido)
    if sha_descargado != sha_esperado:
        raise CierreVerificacionError(
            f"El SHA-256 de '{ruta_archivo}' descargado ({sha_descargado}) no coincide con el publicado "
            f"({sha_esperado}); aborto el cierre de {_clave_mes(year, month)} sin tocar la base viva."
        )

    try:
        hojas_descargadas = archive.leer_libro_cierre(contenido)
    except Exception as exc:  # archivo corrupto / no legible como .xlsx
        raise CierreVerificacionError(
            f"No se pudo leer '{ruta_archivo}' recién publicado como .xlsx: {exc}; aborto el cierre de "
            f"{_clave_mes(year, month)} sin tocar la base viva."
        ) from exc

    for nombre, df_esperado in snapshot.items():
        df_descargado = hojas_descargadas.get(nombre)
        if df_descargado is None:
            raise CierreVerificacionError(
                f"La hoja '{nombre}' no está en '{ruta_archivo}' verificado; aborto el cierre de "
                f"{_clave_mes(year, month)} sin tocar la base viva."
            )
        if len(df_descargado) != len(df_esperado):
            raise CierreVerificacionError(
                f"La hoja '{nombre}' tiene {len(df_descargado)} filas en '{ruta_archivo}' pero el snapshot "
                f"construido desde la base viva tiene {len(df_esperado)}; aborto el cierre de "
                f"{_clave_mes(year, month)} sin tocar la base viva."
            )

    with storage.transaction() as tx:
        tx.set_config(
            "cierre::progreso",
            json.dumps(
                {"year": year, "month": month, "paso": "verificado", "archivo": nombre_archivo, "sha256": sha_esperado}
            ),
        )


# ------------------------------------------------------------- paso 4


def _paso4_aplicar(
    storage, rol: str, year: int, month: int, nombre_archivo: str, sha: str, snapshot: dict[str, pd.DataFrame]
) -> ResultadoCierre:
    """ÚNICA mutación de la base viva (§8, paso 4), dentro de UNA
    transacción: quita las filas del mes M de las 7 hojas transaccionales,
    escribe un movimiento "apertura" por cada producto con `stock_cierre
    != 0` (fecha = 00:00 Bogotá del día 1 de M+1, que es exactamente `fin`
    de `month_bounds_utc(year, month)`), actualiza
    `config["ultimo_mes_cerrado"]` y registra `auditoria`. Por R6: si algo
    falla a mitad de esta transacción, no queda NADA a medias."""
    inicio, fin = month_bounds_utc(year, month)
    inicio_local = date(year, month, 1)
    fin_local = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    with storage.transaction() as tx:
        requerir(rol, "cerrar_mes")  # revalidado también aquí, justo antes de mutar (defensivo, R§10)

        for hoja in schema.HOJAS_TRANSACCIONALES_MENSUALES:
            df = tx.read_sheet(hoja)
            if hoja == schema.CUADRE_CAJA:

                def _fuera_de_rango_local(valor: object) -> bool:
                    try:
                        d = date.fromisoformat(str(valor)[:10])
                    except ValueError:
                        return True  # no se puede clasificar: se conserva, nunca se borra a ciegas
                    return not (inicio_local <= d < fin_local)

                conservar = df["fecha_local"].map(_fuera_de_rango_local)
            elif hoja == schema.VENTA_ITEMS:
                ids_del_mes = set(snapshot[schema.VENTAS]["id"])
                conservar = ~df["venta_id"].isin(ids_del_mes)
            elif hoja == schema.DEVOLUCION_ITEMS:
                ids_del_mes = set(snapshot[schema.DEVOLUCIONES]["id"])
                conservar = ~df["devolucion_id"].isin(ids_del_mes)
            else:

                def _fuera_de_rango_utc(valor: object) -> bool:
                    f = _parse_o_none(valor)
                    return f is None or not (inicio <= f < fin)  # no clasificable: se conserva

                conservar = df["fecha_hora_utc"].map(_fuera_de_rango_utc)
            tx.write_sheet(hoja, df[conservar].reset_index(drop=True))

        ahora = to_iso_utc(now_utc())
        fecha_apertura = to_iso_utc(fin)  # 00:00 Bogotá del día 1 de M+1 == `fin` de month_bounds_utc(M)
        nuevas_aperturas = []
        for _, fila in snapshot["stock_cierre"].iterrows():
            cantidad = _to_int(fila["cantidad"])
            if cantidad == 0:
                continue  # §8: solo se abre movimiento para productos con stock != 0
            producto_id = fila["producto_id"]
            sede_id = fila["sede_id"]
            nuevas_aperturas.append(
                {
                    "id": f"APC-{_clave_mes(year, month)}-{producto_id}-{sede_id}",
                    "fecha_hora_utc": fecha_apertura,
                    "producto_id": producto_id,
                    "sede_id": sede_id,
                    "tipo": "apertura",
                    "cantidad": cantidad,
                    "stock_antes": 0,
                    "stock_despues": cantidad,
                    "costo_unitario": _to_int(fila["costo"]),
                    "ref_tipo": "cierre_mensual",
                    "ref_id": _clave_mes(year, month),
                    "proveedor_id": "",
                    "documento_ref": nombre_archivo,
                    "usuario_id": "sistema:cierre_mensual",
                    "nota": excel_safe(f"Apertura de inventario por cierre de {_clave_mes(year, month)}"),
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
        if nuevas_aperturas:
            movimientos_pruned = tx.read_sheet(schema.MOVIMIENTOS)
            tx.write_sheet(
                schema.MOVIMIENTOS, pd.concat([movimientos_pruned, pd.DataFrame(nuevas_aperturas)], ignore_index=True)
            )

        tx.set_config("ultimo_mes_cerrado", _clave_mes(year, month))
        tx.set_config(
            "cierre::progreso",
            json.dumps({"year": year, "month": month, "paso": "aplicado", "archivo": nombre_archivo, "sha256": sha}),
        )

        auditoria = tx.read_sheet(schema.AUDITORIA)
        nueva_auditoria = pd.DataFrame(
            [
                {
                    "id": f"AUD-cierre-{_clave_mes(year, month)}",
                    "ts": ahora,
                    "usuario": excel_safe(rol, field_name="usuario"),
                    "accion": "cerrar_mes",
                    "detalle": excel_safe(
                        f"Cierre de {_clave_mes(year, month)}: archivo={nombre_archivo}, sha256={sha}, "
                        f"movimientos_apertura={len(nuevas_aperturas)}."
                    ),
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            ]
        )
        tx.write_sheet(schema.AUDITORIA, pd.concat([auditoria, nueva_auditoria], ignore_index=True))

    filas_por_hoja = {nombre: int(len(snapshot[nombre])) for nombre in schema.HOJAS_TRANSACCIONALES_MENSUALES}
    return ResultadoCierre(
        year=year,
        month=month,
        ya_estaba_cerrado=False,
        archivo=nombre_archivo,
        sha256=sha,
        filas_por_hoja=filas_por_hoja,
        movimientos_apertura=len(nuevas_aperturas),
        mensaje=f"Cierre de {_clave_mes(year, month)} completado: {len(nuevas_aperturas)} movimientos de apertura.",
    )


# ------------------------------------------------------------- API pública


def cerrar_mes(storage, rol: str, year: int, month: int) -> ResultadoCierre:
    """Cierra y archiva el mes `year-month` (§8): construye el snapshot,
    lo publica y verifica en OlaTata-Archive, y solo si la verificación
    pasa, vacía la base viva en una sola transacción.

    - Requiere la capacidad `cerrar_mes` (§10: solo `admin`).
    - Si `(year, month)` es el mes en curso (o futuro) en Bogotá, lanza
      `CierreMesInvalidoError`: "JAMÁS cierra el mes en curso".
    - Si `(year, month)` ya estaba cerrado (`config["ultimo_mes_cerrado"]`
      lo cubre), es un no-op idempotente: NO lanza, devuelve
      `ResultadoCierre(ya_estaba_cerrado=True)`.
    - Si la verificación del paso 3 falla, lanza `CierreVerificacionError`
      y la base viva queda intacta (los pasos 1-3 nunca la tocan).
    """
    requerir(rol, "cerrar_mes")

    if _ya_cerrado(storage, year, month):
        return ResultadoCierre(
            year=year,
            month=month,
            ya_estaba_cerrado=True,
            mensaje=f"{_clave_mes(year, month)} ya estaba cerrado; no se repite ninguna acción.",
        )

    _validar_mes_cerrable(year, month)

    snapshot = _paso1_construir_snapshot(storage, year, month)
    nombre_archivo, sha = _paso2_publicar(storage, year, month, snapshot)
    _paso3_verificar(storage, year, month, nombre_archivo, sha, snapshot)
    return _paso4_aplicar(storage, rol, year, month, nombre_archivo, sha, snapshot)
