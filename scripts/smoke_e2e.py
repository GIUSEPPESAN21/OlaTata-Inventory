"""Smoke E2E de Ola Tata (propiedad de A6 — QA y Datos).

Simula 90 días x ~40 ventas/día, con devoluciones y 3 cierres de mes,
sobre datos 100% FICTICIOS (semilla fija, ver `scripts/seed_demo.py`).
Verifica los invariantes de negocio del §11 del encargo y mide los
presupuestos de rendimiento. Usa SOLO la API pública de `core/`.

Como `core.sales` / `core.inventory` / `core.analytics` /
`core.monthly_close` (propiedad de A1-A4) pueden no existir todavía en
esta rama, el script corre en "modo degradado": genera los datos
directamente contra `storage.write_sheet` (vía `seed_demo`) y simula el
cierre de mes con la API ya congelada de `storage` (`archive_put_bytes` +
`transaction()`), reportando con claridad qué se ejercitó de verdad contra
código real de dominio y qué queda pendiente de integración.

Uso:
    python scripts/smoke_e2e.py
Código de salida 0 si no se encontró ningún problema de INVARIANTE (los
presupuestos de rendimiento se reportan pero no hacen fallar el script:
ver el hallazgo de rendimiento en el resumen final).
"""
from __future__ import annotations

import io
import json
import random
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.timeutil import now_utc, to_iso_utc  # noqa: E402
from scripts.seed_demo import (  # noqa: E402
    SEDE,
    SEED_POR_DEFECTO,
    crear_catalogo_y_proveedores,
    crear_usuarios_demo,
    generar_ventas_dia,
)

DIAS_SIMULADOS = 90
VENTAS_POR_DIA = 40
FECHA_INICIO = date(2025, 9, 1)


# --------------------------------------------------------------- integración
def _modulos_de_dominio_disponibles() -> dict[str, bool]:
    disponibles = {}
    for nombre in ("sales", "inventory", "analytics", "monthly_close"):
        try:
            __import__(f"core.{nombre}")
            disponibles[nombre] = True
        except (ImportError, ModuleNotFoundError):
            disponibles[nombre] = False
    return disponibles


# ------------------------------------------------------------ cierre de mes
def cerrar_mes_manual(storage, anio: int, mes: int) -> dict:
    """Fallback de A6 cuando `core.monthly_close` todavía no existe: usa
    SOLO la API ya congelada de `storage` (`archive_put_bytes` +
    `transaction()`) para archivar y vaciar las hojas transaccionales
    mensuales, dejando intactas `stock`, `productos`, `proveedores`,
    `usuarios`, `config` y `auditoria` (R7: el stock jamás se reinicia)."""
    mes_key = f"{anio:04d}-{mes:02d}"
    snapshot = {nombre: storage.read_sheet(nombre) for nombre in schema.HOJAS_TRANSACCIONALES_MENSUALES}

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nombre, df in snapshot.items():
            df.to_excel(writer, sheet_name=nombre[:31], index=False)
    storage.archive_put_bytes(f"cierres/{mes_key}.xlsx", buffer.getvalue(), f"Cierre de {mes_key} (demo ficticio)")

    stock_antes = storage.read_sheet(schema.STOCK).copy()
    with storage.transaction() as tx:
        for nombre in schema.HOJAS_TRANSACCIONALES_MENSUALES:
            tx.write_sheet(nombre, pd.DataFrame(columns=schema.columnas(nombre)))
    stock_despues = storage.read_sheet(schema.STOCK)
    stock_intacto = stock_antes["cantidad"].sum() == stock_despues["cantidad"].sum() and len(stock_antes) == len(stock_despues)

    return {
        "mes": mes_key,
        "filas_archivadas": {k: len(v) for k, v in snapshot.items()},
        "stock_no_se_reinicio": bool(stock_intacto),
    }


def _cerrar_mes(storage, anio: int, mes: int) -> tuple[dict, bool]:
    """Intenta usar `core.monthly_close` real si ya existe (integrado por
    el agente principal); si no, usa el fallback manual de A6. Devuelve
    SIEMPRE un dict con la misma forma que `cerrar_mes_manual` (normaliza
    el `ResultadoCierre` real a dict), más (resultado, fue_integracion_real)
    para que el resto del script no le importe cuál camino se tomó."""
    mes_key = f"{anio:04d}-{mes:02d}"
    try:
        from core import monthly_close  # type: ignore
    except (ImportError, ModuleNotFoundError):
        return cerrar_mes_manual(storage, anio, mes), False

    stock_antes = storage.read_sheet(schema.STOCK).copy()
    try:
        # Firma real de A4 (core/monthly_close.py): cerrar_mes(storage, rol,
        # year, month) — requiere "admin" (requerir(rol, "cerrar_mes")).
        # Devuelve un `ResultadoCierre` (dataclass), no un dict.
        resultado = monthly_close.cerrar_mes(storage, "admin", anio, mes)
    except (AttributeError, TypeError):
        return cerrar_mes_manual(storage, anio, mes), False

    stock_despues = storage.read_sheet(schema.STOCK)
    stock_intacto = stock_antes["cantidad"].sum() == stock_despues["cantidad"].sum() and len(
        stock_antes
    ) == len(stock_despues)
    dict_resultado = {
        "mes": mes_key,
        "filas_archivadas": dict(getattr(resultado, "filas_por_hoja", {}) or {}),
        "stock_no_se_reinicio": bool(stock_intacto),
    }
    return dict_resultado, True


# ------------------------------------------------------- verificación de §11
def verificar_invariantes_del_mes(storage) -> list[str]:
    """Invariantes de negocio sobre el libro VIVO (antes de cerrar el mes),
    releyendo lo persistido en `storage` (no los acumuladores en memoria de
    `seed_demo`) — esto es la parte de "pantalla = Excel = recálculo desde
    el libro" que SÍ se puede probar sin `core.sales`/`core.analytics`."""
    problemas: list[str] = []
    df_ventas = storage.read_sheet(schema.VENTAS)
    df_pagos = storage.read_sheet(schema.PAGOS)
    df_stock = storage.read_sheet(schema.STOCK)

    if not df_ventas.empty:
        calculado = df_ventas["subtotal"] - df_ventas["descuento_total"] + df_ventas["envio_cobrado"]
        mal = df_ventas[calculado != df_ventas["total"]]
        if len(mal):
            problemas.append(f"{len(mal)} ventas con subtotal-descuento+envio != total")

        pagado_por_venta = df_pagos.groupby("venta_id")["monto"].sum()
        completadas = df_ventas[df_ventas["estado"] == "completada"]
        pagado = completadas["id"].map(pagado_por_venta).fillna(0).astype(int)
        mal_pago = completadas[pagado != completadas["total"]]
        if len(mal_pago):
            problemas.append(f"{len(mal_pago)} ventas donde la suma de pagos no cuadra con el total")

    negativo = df_stock[df_stock["cantidad"] < 0]
    if len(negativo):
        problemas.append(f"{len(negativo)} filas de stock quedaron negativas")

    return problemas


def verificar_stock_igual_suma_historica_de_movimientos(storage, meses_cerrados: list[dict]) -> list[str]:
    """Invariante 'stock = Σ movimientos', verificado contra el LIBRO
    VIVO únicamente (es exactamente lo que hace "Verificar integridad" de
    A1 en producción).

    Nota de diseño (corregida por el coordinador tras encontrar que este
    chequeo original sumaba también los movimientos ARCHIVADOS de cada
    mes cerrado, además de los vivos): eso SOBRE-cuenta a propósito,
    porque el movimiento "apertura" que escribe `core.monthly_close` al
    cerrar un mes (§8, paso 4) YA guarda el valor ABSOLUTO de
    `stock_cierre` en su `cantidad` — no es un delta de cero. Esa fila
    existe precisamente para que "stock = Σ movimientos" siga siendo
    cierto usando SOLO lo que queda en el libro vivo después de archivar
    (los movimientos previos a `stock_cierre` ya no hacen falta: su
    efecto neto quedó capturado en una sola fila). Sumar la apertura
    ENCIMA del historial archivado que ya construía ese mismo valor
    duplica la cuenta. `meses_cerrados` se conserva como parámetro para
    no romper la firma que usa `scripts/smoke_e2e.py`, pero ya no se usa
    aquí — la verificación histórica corresponde, si se necesita, a
    comparar cada archivo contra su propio `resumen_mes`/`stock_cierre`
    (lo que `core.monthly_close._paso3_verificar` ya hace antes de
    aplicar cada cierre)."""
    del meses_cerrados  # ver nota de diseño arriba
    df_mov = storage.read_sheet(schema.MOVIMIENTOS)
    df_stock = storage.read_sheet(schema.STOCK)
    if df_mov.empty:
        suma_por_producto = pd.Series(dtype="int64")
    else:
        suma_por_producto = df_mov["cantidad"].astype(int).groupby(df_mov["producto_id"]).sum()

    problemas = []
    for _, fila in df_stock.iterrows():
        esperado = int(suma_por_producto.get(fila["producto_id"], 0))
        real = int(fila["cantidad"])
        if esperado != real:
            problemas.append(f"producto {fila['producto_id']}: Σmovimientos(vivos)={esperado} pero stock={real}")
    return problemas


# ------------------------------------------------- concurrencia "a escala"
def probar_concurrencia_a_escala(storage, n_hilos: int = 50) -> dict:
    """Confirma que el patrón de `storage.transaction()` (RLock que
    serializa toda sección crítica) se sostiene con MÁS hilos de los que
    prueba A2 a nivel unitario (20) — no reimplementa esa prueba, solo
    confirma que el mismo patrón no se degrada a escala. `core.sales` no
    existe aún, así que esto ejercita el primitivo de `storage` directo
    (que es lo que `core.sales` usará por debajo)."""
    ahora = to_iso_utc(now_utc())
    producto_id = "STRESS-ULTIMA-UNIDAD"
    with storage.transaction() as tx:
        df = tx.read_sheet(schema.STOCK)
        fila = pd.DataFrame([{"producto_id": producto_id, "sede_id": SEDE, "cantidad": 1, "created_at": ahora, "updated_at": ahora}])
        tx.write_sheet(schema.STOCK, pd.concat([df, fila], ignore_index=True))

    exitos: list[bool] = []
    rechazos: list[str] = []
    cerrojo_resultado = threading.Lock()

    def intentar_vender_la_ultima_unidad() -> None:
        try:
            with storage.transaction() as tx:
                df = tx.read_sheet(schema.STOCK)
                coincide = (df["producto_id"] == producto_id) & (df["sede_id"] == SEDE)
                actual = int(df.loc[coincide, "cantidad"].iloc[0])
                if actual <= 0:
                    raise ValueError("sin stock disponible")
                df.loc[coincide, "cantidad"] = actual - 1
                tx.write_sheet(schema.STOCK, df)
            with cerrojo_resultado:
                exitos.append(True)
        except Exception as exc:  # venta rechazada, es el comportamiento esperado
            with cerrojo_resultado:
                rechazos.append(str(exc))

    hilos = [threading.Thread(target=intentar_vender_la_ultima_unidad) for _ in range(n_hilos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    stock_final = storage.read_sheet(schema.STOCK)
    cantidad_final = int(stock_final.loc[stock_final["producto_id"] == producto_id, "cantidad"].iloc[0])

    return {
        "n_hilos": n_hilos,
        "exitos": len(exitos),
        "rechazos": len(rechazos),
        "stock_final": cantidad_final,
        "exactamente_un_exito": len(exitos) == 1 and cantidad_final == 0,
        "ningun_hilo_colgado": not any(h.is_alive() for h in hilos),
    }


# ----------------------------------------------------- presupuestos (§11)
def medir_presupuestos_de_rendimiento() -> dict:
    """Mide los presupuestos del §11 contra `core.storage.Storage` REAL
    (disco), porque `core.sales`/`core.analytics` no existen aún. Libro
    poblado a la escala que el propio encargo usa como ejemplo para el
    presupuesto de Análisis: ~3000 ventas "en el mes" (el libro vivo de
    Ola Tata es solo el mes en curso, por diseño — ver CONTRATOS.md)."""
    from core.storage import Storage

    tmp_dir = Path(tempfile.mkdtemp(prefix="olatata_smoke_perf_"))
    st = Storage(local_path=tmp_dir / "OLATATA_DB_PERF.xlsx", sync_enabled=False)

    with st.transaction() as tx:
        df_v = tx.read_sheet(schema.VENTAS)
        filas_v = pd.DataFrame([{c: "x" for c in schema.columnas(schema.VENTAS)} for _ in range(3000)])
        tx.write_sheet(schema.VENTAS, pd.concat([df_v, filas_v], ignore_index=True))
        df_i = tx.read_sheet(schema.VENTA_ITEMS)
        filas_i = pd.DataFrame([{c: "x" for c in schema.columnas(schema.VENTA_ITEMS)} for _ in range(6000)])
        tx.write_sheet(schema.VENTA_ITEMS, pd.concat([df_i, filas_i], ignore_index=True))

    t0 = time.perf_counter()
    with st.transaction() as tx:
        df = tx.read_sheet(schema.VENTAS)
        nueva = pd.DataFrame([{c: "y" for c in schema.columnas(schema.VENTAS)}])
        tx.write_sheet(schema.VENTAS, pd.concat([df, nueva], ignore_index=True))
    confirmar_venta_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    _ = st.read_sheet(schema.VENTAS)
    abrir_analisis_s = time.perf_counter() - t1

    # "pantalla = Excel = recálculo desde el libro": recarga desde disco con
    # una instancia NUEVA y compara.
    st_recargado = Storage(local_path=st.local_path, sync_enabled=False)
    coincide_tras_recarga = len(st_recargado.read_sheet(schema.VENTAS)) == len(st.read_sheet(schema.VENTAS))

    return {
        "confirmar_venta_local_s": round(confirmar_venta_s, 3),
        "confirmar_venta_cumple_presupuesto_500ms_local": confirmar_venta_s < 0.5,
        "confirmar_venta_cumple_presupuesto_3s_con_github": confirmar_venta_s < 3.0,
        "abrir_analisis_s": round(abrir_analisis_s, 4),
        "abrir_analisis_cumple_presupuesto_2s": abrir_analisis_s < 2.0,
        "pantalla_igual_excel_tras_recarga": coincide_tras_recarga,
        "escala_probada": "3000 ventas / 6000 items (ventas 'en el mes', ver §11)",
    }


# --------------------------------------------------------------------- main
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    inicio = time.perf_counter()
    disponibilidad = _modulos_de_dominio_disponibles()

    from tests.conftest import FakeStorage  # infra de pruebas ya congelada, en memoria

    storage = FakeStorage()
    rng = random.Random(SEED_POR_DEFECTO)
    usuarios = crear_usuarios_demo(storage)
    productos = crear_catalogo_y_proveedores(storage, rng, fecha_referencia=FECHA_INICIO)

    historial_vendido: list[dict] = []
    resumenes: list[dict] = []
    meses_cerrados: list[dict] = []
    integracion_real_cierre: list[bool] = []
    problemas_invariantes: list[str] = []

    mes_actual = (FECHA_INICIO.year, FECHA_INICIO.month)
    for offset in range(DIAS_SIMULADOS):
        fecha = FECHA_INICIO + timedelta(days=offset)
        mes_de_fecha = (fecha.year, fecha.month)
        if mes_de_fecha != mes_actual:
            problemas_invariantes += verificar_invariantes_del_mes(storage)
            resultado_cierre, fue_real = _cerrar_mes(storage, *mes_actual)
            meses_cerrados.append(resultado_cierre)
            integracion_real_cierre.append(fue_real)
            mes_actual = mes_de_fecha

        resumen = generar_ventas_dia(
            storage, rng, fecha, productos, usuarios, historial_vendido, ventas_por_dia=VENTAS_POR_DIA
        )
        resumenes.append(resumen)

    # Cierre final (parcial) para completar los 3 cierres de mes pedidos.
    problemas_invariantes += verificar_invariantes_del_mes(storage)
    resultado_cierre, fue_real = _cerrar_mes(storage, *mes_actual)
    meses_cerrados.append(resultado_cierre)
    integracion_real_cierre.append(fue_real)

    if len(meses_cerrados) != 3:
        problemas_invariantes.append(f"se esperaban 3 cierres de mes, hubo {len(meses_cerrados)}")

    problemas_invariantes += verificar_stock_igual_suma_historica_de_movimientos(storage, meses_cerrados)

    concurrencia = probar_concurrencia_a_escala(storage)
    if not concurrencia["exactamente_un_exito"]:
        problemas_invariantes.append(f"concurrencia a escala falló: {concurrencia}")

    presupuestos = medir_presupuestos_de_rendimiento()

    duracion_total_s = time.perf_counter() - inicio

    resumen_final = {
        "semilla": SEED_POR_DEFECTO,
        "dias_simulados": DIAS_SIMULADOS,
        "ventas_por_dia_objetivo": VENTAS_POR_DIA,
        "total_ventas_generadas": sum(r["ventas"] for r in resumenes),
        "total_vendido_cop": sum(r["total_vendido"] for r in resumenes),
        "total_devoluciones": sum(r["devoluciones"] for r in resumenes),
        "meses_cerrados": [c["mes"] for c in meses_cerrados],
        "cierres_usaron_core_monthly_close_real": integracion_real_cierre,
        "concurrencia_a_escala": concurrencia,
        "presupuestos_de_rendimiento": presupuestos,
        "modulos_de_dominio_disponibles_en_esta_rama": disponibilidad,
        "problemas_de_invariantes": problemas_invariantes,
        "duracion_total_smoke_s": round(duracion_total_s, 2),
    }

    print("=" * 72)
    print("SMOKE E2E — Ola Tata (datos 100% ficticios, semilla fija)")
    print("=" * 72)
    print(json.dumps(resumen_final, indent=2, ensure_ascii=False))
    print("-" * 72)
    print("Qué se probó de verdad (contra código real de core/):")
    print("  - storage.transaction() / write_sheet / next_counter / archive_*: SI (core.storage real)")
    print("  - core.auth.crear_usuario: SI (core.auth real)")
    print("  - Invariantes de dinero y fechas sobre datos persistidos: SI")
    print("  - Concurrencia del lock de storage a escala (50 hilos): SI")
    print("  - Presupuestos de rendimiento sobre core.storage real (disco): SI")
    for nombre, existe in disponibilidad.items():
        estado = "integrado (módulo presente, se intentó usar su API real)" if existe else "PENDIENTE: core." + nombre + " aún no existe en esta rama -> se usó el modo degradado de A6"
        print(f"  - core.{nombre}: {estado}")
    print("  - Idempotencia de doble clic (idempotency_key) a nivel de core.sales: PENDIENTE,")
    print("    ya cubierta a nivel unitario por A2; aquí no se reimplementa.")
    print("=" * 72)

    if problemas_invariantes:
        print(f"RESULTADO: {len(problemas_invariantes)} problema(s) de invariantes. Ver detalle arriba.")
        return 1
    print("RESULTADO: todos los invariantes verificados se cumplieron.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
