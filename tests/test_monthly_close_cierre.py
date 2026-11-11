"""Pruebas de `core/monthly_close.py` (§8, cierre mensual).

Escenario común (`_poblar_junio_2020`): un mes M = junio 2020 (bien en el
pasado, para no depender de la fecha real de ejecución) con 4 productos,
ventas, pagos, devoluciones y cuadre de caja de junio, MÁS movimientos de
mayo (mes anterior, para probar que `stock_cierre` mira hacia atrás) y de
julio (mes siguiente, YA registrados antes del cierre, para probar que
sobreviven intactos).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from core import archive, monthly_close, schema
from core.permissions import PermisoDenegadoError
from core.timeutil import BOGOTA, local_date, now_utc, parse_iso_utc, to_iso_utc


def _utc_iso(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> str:
    local = datetime(year, month, day, hour, minute, tzinfo=BOGOTA)
    return to_iso_utc(local)


# ------------------------------------------------------- filas de ejemplo


def _fila_producto(id_, nombre, costo, precio):
    return {
        "id": id_,
        "nombre": nombre,
        "categoria": "Bolsos",
        "color": "Negro",
        "talla_tamano": "",
        "proveedor_id": "",
        "costo": costo,
        "precio": precio,
        "stock_minimo": 1,
        "codigo_barras": "",
        "activo": True,
        "created_at": "",
        "updated_at": "",
    }


def _fila_movimiento(id_, fecha_iso, producto_id, tipo, cantidad, stock_antes, stock_despues, costo_unitario, ref_tipo="", ref_id=""):
    return {
        "id": id_,
        "fecha_hora_utc": fecha_iso,
        "producto_id": producto_id,
        "sede_id": schema.SEDE_PRINCIPAL,
        "tipo": tipo,
        "cantidad": cantidad,
        "stock_antes": stock_antes,
        "stock_despues": stock_despues,
        "costo_unitario": costo_unitario,
        "ref_tipo": ref_tipo,
        "ref_id": ref_id,
        "proveedor_id": "",
        "documento_ref": "",
        "usuario_id": "u1",
        "nota": "",
        "created_at": "",
        "updated_at": "",
    }


def _fila_venta(id_, numero, fecha_iso, fecha_local, estado, total):
    return {
        "id": id_,
        "numero": numero,
        "fecha_hora_utc": fecha_iso,
        "fecha_local": fecha_local,
        "sede_id": schema.SEDE_PRINCIPAL,
        "canal": "tienda",
        "cliente_nombre": "",
        "cliente_telefono": "",
        "subtotal": total,
        "descuento_total": 0,
        "envio_cobrado": 0,
        "envio_ciudad": "",
        "envio_transportadora": "",
        "envio_guia": "",
        "total": total,
        "estado": estado,
        "anulada_por": "",
        "anulada_motivo": "",
        "anulada_at": "",
        "vendedor_id": "u1",
        "vendedor_nombre": "Vendedor Uno",
        "idempotency_key": id_,
        "nota": "",
        "created_at": "",
        "updated_at": "",
    }


def _fila_venta_item(id_, venta_id, producto_id, nombre_snapshot, cantidad, precio_unitario, costo_unitario):
    return {
        "id": id_,
        "venta_id": venta_id,
        "producto_id": producto_id,
        "nombre_snapshot": nombre_snapshot,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
        "descuento_linea": 0,
        "costo_unitario": costo_unitario,
        "total_linea": cantidad * precio_unitario,
        "created_at": "",
        "updated_at": "",
    }


def _fila_pago(id_, venta_id, metodo, monto, fecha_iso):
    return {
        "id": id_,
        "venta_id": venta_id,
        "metodo": metodo,
        "monto": monto,
        "referencia": "",
        "fecha_hora_utc": fecha_iso,
        "created_at": "",
        "updated_at": "",
    }


def _fila_devolucion(id_, numero, venta_numero, fecha_iso, fecha_local, tipo, reembolso_monto):
    return {
        "id": id_,
        "numero": numero,
        "venta_numero": venta_numero,
        "fecha_hora_utc": fecha_iso,
        "fecha_local": fecha_local,
        "tipo": tipo,
        "motivo": "",
        "reembolso_metodo": "efectivo",
        "reembolso_monto": reembolso_monto,
        "usuario_id": "u1",
        "created_at": "",
        "updated_at": "",
    }


def _fila_devolucion_item(id_, devolucion_id, producto_id, nombre_snapshot, cantidad, precio_unitario, costo_unitario, destino):
    return {
        "id": id_,
        "devolucion_id": devolucion_id,
        "producto_id": producto_id,
        "nombre_snapshot": nombre_snapshot,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
        "costo_unitario": costo_unitario,
        "destino": destino,
        "created_at": "",
        "updated_at": "",
    }


def _fila_cuadre(id_, fecha_local, base_inicial, efectivo_esperado, efectivo_contado):
    return {
        "id": id_,
        "fecha_local": fecha_local,
        "sede_id": schema.SEDE_PRINCIPAL,
        "base_inicial": base_inicial,
        "efectivo_esperado": efectivo_esperado,
        "efectivo_contado": efectivo_contado,
        "diferencia": efectivo_contado - efectivo_esperado,
        "nota": "",
        "usuario_id": "u1",
        "created_at": "",
        "updated_at": "",
    }


def _poblar_junio_2020(storage) -> None:
    """P1: entra en junio, se vende parcialmente en junio y OTRA VEZ en
    julio (antes del cierre). P2: entra en junio, sin más movimiento. P3:
    su único movimiento es un "apertura" fechado justo al INICIO de junio
    (00:00 Bogotá del día 1 — como si viniera de un cierre de mayo ya
    hecho), sin ninguna otra actividad en junio — prueba que
    `stock_cierre` encuentra el último `stock_despues` aunque no haya
    ningún movimiento "fresco" dentro del mes, y que ese movimiento SÍ
    cae dentro del rango de junio (se archiva y se reemplaza por la
    apertura de julio, sin dejar un movimiento huérfano de un mes no
    cerrado). P4: entra y se vende por completo en junio (queda en 0, sin
    apertura)."""
    with storage.transaction() as tx:
        tx.write_sheet(
            schema.PRODUCTOS,
            pd.DataFrame(
                [
                    _fila_producto("P1", "Bolso tote", 1000, 2000),
                    _fila_producto("P2", "Bolso cruzado", 2000, 4000),
                    _fila_producto("P3", "Billetera", 500, 1000),
                    _fila_producto("P4", "Cartera mini", 800, 1500),
                ]
            ),
        )
        tx.write_sheet(
            schema.MOVIMIENTOS,
            pd.DataFrame(
                [
                    _fila_movimiento("M-01", _utc_iso(2020, 6, 1, 0, 0), "P3", "apertura", 4, 0, 4, 500),
                    _fila_movimiento("M-02", _utc_iso(2020, 6, 1), "P1", "entrada", 10, 0, 10, 1000),
                    _fila_movimiento("M-03", _utc_iso(2020, 6, 10), "P1", "venta", -3, 10, 7, 1000, "venta", "V-1"),
                    _fila_movimiento("M-04", _utc_iso(2020, 6, 2), "P2", "entrada", 5, 0, 5, 2000),
                    _fila_movimiento("M-05", _utc_iso(2020, 6, 3), "P4", "entrada", 6, 0, 6, 800),
                    _fila_movimiento("M-06", _utc_iso(2020, 6, 4), "P4", "venta", -6, 6, 0, 800, "venta", "V-x"),
                    _fila_movimiento("M-07", _utc_iso(2020, 7, 2), "P1", "venta", -2, 7, 5, 1000, "venta", "V-3"),
                ]
            ),
        )
        tx.write_sheet(
            schema.VENTAS,
            pd.DataFrame(
                [
                    _fila_venta("V-1", "2020-06-0001", _utc_iso(2020, 6, 10), "2020-06-10", "completada", 6000),
                    _fila_venta("V-2", "2020-06-0002", _utc_iso(2020, 6, 15), "2020-06-15", "anulada", 4000),
                    _fila_venta("V-3", "2020-07-0001", _utc_iso(2020, 7, 2), "2020-07-02", "completada", 4000),
                ]
            ),
        )
        tx.write_sheet(
            schema.VENTA_ITEMS,
            pd.DataFrame(
                [
                    _fila_venta_item("VI-1", "V-1", "P1", "Bolso tote", 3, 2000, 1000),
                    _fila_venta_item("VI-2", "V-2", "P2", "Bolso cruzado", 2, 2000, 2000),
                    _fila_venta_item("VI-3", "V-3", "P1", "Bolso tote", 2, 2000, 1000),
                ]
            ),
        )
        tx.write_sheet(
            schema.PAGOS,
            pd.DataFrame(
                [
                    _fila_pago("PG-1", "V-1", "efectivo", 6000, _utc_iso(2020, 6, 10)),
                    _fila_pago("PG-2", "V-3", "efectivo", 4000, _utc_iso(2020, 7, 2)),
                ]
            ),
        )
        tx.write_sheet(
            schema.DEVOLUCIONES,
            pd.DataFrame(
                [
                    _fila_devolucion(
                        "D-1", "2020-06-D0001", "2020-06-0001", _utc_iso(2020, 6, 20), "2020-06-20", "devolucion", 2000
                    )
                ]
            ),
        )
        tx.write_sheet(
            schema.DEVOLUCION_ITEMS,
            pd.DataFrame([_fila_devolucion_item("DI-1", "D-1", "P1", "Bolso tote", 1, 2000, 1000, "reingreso")]),
        )
        tx.write_sheet(
            schema.CUADRE_CAJA,
            pd.DataFrame(
                [
                    _fila_cuadre("CC-1", "2020-06-10", 0, 6000, 6000),
                    _fila_cuadre("CC-2", "2020-07-02", 0, 4000, 4000),
                ]
            ),
        )


FILAS_ESPERADAS_JUNIO = {
    schema.VENTAS: 2,
    schema.VENTA_ITEMS: 2,
    schema.PAGOS: 1,
    schema.DEVOLUCIONES: 1,
    schema.DEVOLUCION_ITEMS: 1,
    schema.MOVIMIENTOS: 6,
    schema.CUADRE_CAJA: 1,
}


def _verificar_invariante_stock(movimientos: pd.DataFrame) -> None:
    """R4: para cada (producto_id, sede_id), la cadena stock_antes ->
    stock_despues debe ser consistente y arrancar en 0 (base viva recién
    cerrada: no debe quedar ningún movimiento "huérfano" de un mes ya
    archivado)."""
    if movimientos.empty:
        return
    movimientos = movimientos.copy()
    movimientos["_fecha"] = movimientos["fecha_hora_utc"].map(parse_iso_utc)
    for (producto_id, sede_id), grupo in movimientos.groupby(["producto_id", "sede_id"]):
        grupo = grupo.sort_values("_fecha", kind="stable")
        esperado = 0
        for _, fila in grupo.iterrows():
            assert int(fila["stock_antes"]) == esperado, (
                f"Cadena de movimientos rota para {producto_id}/{sede_id}: fila {fila['id']} tiene "
                f"stock_antes={fila['stock_antes']}, esperaba {esperado}"
            )
            esperado = esperado + int(fila["cantidad"])
            assert int(fila["stock_despues"]) == esperado, (
                f"stock_despues inconsistente para {producto_id}/{sede_id} en fila {fila['id']}"
            )


def _assert_cierre_correcto(storage, resultado) -> None:
    assert resultado.ya_estaba_cerrado is False
    assert resultado.archivo == "2020-06.xlsx"
    assert resultado.sha256
    assert resultado.filas_por_hoja == FILAS_ESPERADAS_JUNIO
    assert resultado.movimientos_apertura == 3
    assert storage.get_config("ultimo_mes_cerrado") == "2020-06"

    assert list(storage.read_sheet(schema.VENTAS)["id"]) == ["V-3"]
    assert list(storage.read_sheet(schema.VENTA_ITEMS)["id"]) == ["VI-3"]
    assert list(storage.read_sheet(schema.PAGOS)["id"]) == ["PG-2"]
    assert len(storage.read_sheet(schema.DEVOLUCIONES)) == 0
    assert len(storage.read_sheet(schema.DEVOLUCION_ITEMS)) == 0
    assert list(storage.read_sheet(schema.CUADRE_CAJA)["id"]) == ["CC-2"]

    movimientos_final = storage.read_sheet(schema.MOVIMIENTOS)
    assert len(movimientos_final) == 4  # M-07 (julio, preexistente) + 3 aperturas (M-01 quedó archivado)
    assert "M-07" in set(movimientos_final["id"])
    aperturas = movimientos_final[movimientos_final["tipo"] == "apertura"]
    assert len(aperturas) == 3
    assert set(aperturas["producto_id"]) == {"P1", "P2", "P3"}  # P4 queda en 0: sin apertura
    _verificar_invariante_stock(movimientos_final)

    assert "cierres/2020-06.xlsx" in storage.archive_files
    index = archive.leer_index(storage.archive_files.get("cierres/INDEX.json"))
    entradas = [c for c in index["cierres"] if c["archivo"] == "2020-06.xlsx"]
    assert len(entradas) == 1  # nunca duplicado, incluso tras reintentos
    assert entradas[0]["sha256"] == resultado.sha256
    assert entradas[0]["filas_por_hoja"]["ventas"] == 2

    auditoria = storage.read_sheet(schema.AUDITORIA)
    assert len(auditoria[auditoria["id"] == "AUD-cierre-2020-06"]) == 1


# --------------------------------------------------------- paso 1 (snapshot)


def test_snapshot_filtra_las_7_hojas_por_el_mes_y_calcula_stock_cierre(storage):
    _poblar_junio_2020(storage)
    snapshot = monthly_close._paso1_construir_snapshot(storage, 2020, 6)

    for hoja, esperado in FILAS_ESPERADAS_JUNIO.items():
        assert len(snapshot[hoja]) == esperado, f"hoja {hoja}"

    stock_cierre = snapshot["stock_cierre"].set_index("producto_id")
    assert int(stock_cierre.loc["P1", "cantidad"]) == 7  # mes M, NO incluye la venta de julio
    assert int(stock_cierre.loc["P1", "valor"]) == 7000
    assert int(stock_cierre.loc["P2", "cantidad"]) == 5
    assert int(stock_cierre.loc["P3", "cantidad"]) == 4  # sin movimiento "fresco" en junio
    assert int(stock_cierre.loc["P4", "cantidad"]) == 0  # se vendió por completo

    resumen = snapshot["resumen_mes"].iloc[0]
    assert int(resumen["ventas_completadas"]) == 1
    assert int(resumen["ventas_anuladas"]) == 1
    assert int(resumen["ingresos_netos"]) == 6000
    assert int(resumen["costo_vendido"]) == 3000
    assert int(resumen["ganancia_bruta"]) == 3000
    assert int(resumen["devoluciones_monto"]) == 2000


def test_snapshot_es_puramente_de_lectura_no_modifica_la_base_viva(storage):
    _poblar_junio_2020(storage)
    ventas_antes = storage.read_sheet(schema.VENTAS).copy()
    monthly_close._paso1_construir_snapshot(storage, 2020, 6)
    pd.testing.assert_frame_equal(storage.read_sheet(schema.VENTAS), ventas_antes)
    assert storage.get_config("ultimo_mes_cerrado") is None


# --------------------------------------------------------- cierre completo


def test_cierre_completo_vacia_las_7_hojas_y_preserva_el_inventario(storage):
    _poblar_junio_2020(storage)
    resultado = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    _assert_cierre_correcto(storage, resultado)


def test_movimientos_de_mes_siguiente_registrados_antes_del_cierre_se_conservan_intactos(storage):
    _poblar_junio_2020(storage)
    original = storage.read_sheet(schema.MOVIMIENTOS)
    fila_julio_antes = original[original["id"] == "M-07"].iloc[0].to_dict()

    monthly_close.cerrar_mes(storage, "admin", 2020, 6)

    final = storage.read_sheet(schema.MOVIMIENTOS)
    fila_julio_despues = final[final["id"] == "M-07"].iloc[0].to_dict()
    assert fila_julio_antes == fila_julio_despues


# --------------------------------------------------------- validaciones


def test_vendedor_no_puede_cerrar_mes(storage):
    _poblar_junio_2020(storage)
    with pytest.raises(PermisoDenegadoError):
        monthly_close.cerrar_mes(storage, "vendedor", 2020, 6)
    assert storage.get_config("ultimo_mes_cerrado") is None


def test_no_se_puede_cerrar_el_mes_en_curso(storage):
    _poblar_junio_2020(storage)
    actual = local_date(now_utc())
    with pytest.raises(monthly_close.CierreMesInvalidoError):
        monthly_close.cerrar_mes(storage, "admin", actual.year, actual.month)


def test_no_se_puede_cerrar_un_mes_futuro(storage):
    _poblar_junio_2020(storage)
    actual = local_date(now_utc())
    siguiente_year, siguiente_month = (actual.year + 1, 1) if actual.month == 12 else (actual.year, actual.month + 1)
    with pytest.raises(monthly_close.CierreMesInvalidoError):
        monthly_close.cerrar_mes(storage, "admin", siguiente_year, siguiente_month)


def test_mes_invalido_lanza_error(storage):
    with pytest.raises(monthly_close.CierreMesInvalidoError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 13)


def test_cerrar_un_mes_ya_cerrado_es_no_op_no_falla(storage):
    _poblar_junio_2020(storage)
    primero = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    assert not primero.ya_estaba_cerrado

    ventas_antes = storage.read_sheet(schema.VENTAS).copy()
    movimientos_antes = storage.read_sheet(schema.MOVIMIENTOS).copy()
    index_antes = dict(archive.leer_index(storage.archive_files.get("cierres/INDEX.json")))

    segundo = monthly_close.cerrar_mes(storage, "admin", 2020, 6)

    assert segundo.ya_estaba_cerrado is True
    assert segundo.movimientos_apertura == 0
    pd.testing.assert_frame_equal(storage.read_sheet(schema.VENTAS), ventas_antes)
    pd.testing.assert_frame_equal(storage.read_sheet(schema.MOVIMIENTOS), movimientos_antes)
    assert archive.leer_index(storage.archive_files.get("cierres/INDEX.json")) == index_antes


def test_vendedor_no_puede_cerrar_aunque_el_mes_ya_este_cerrado(storage):
    # El permiso se revalida ANTES de mirar si ya está cerrado.
    _poblar_junio_2020(storage)
    monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    with pytest.raises(PermisoDenegadoError):
        monthly_close.cerrar_mes(storage, "vendedor", 2020, 6)


# --------------------------------------------------- verificación fallida


def test_verificacion_fallida_deja_la_base_viva_completamente_intacta(storage, monkeypatch):
    _poblar_junio_2020(storage)
    original_paso2 = monthly_close._paso2_publicar

    def publicar_y_corromper(storage_, year, month, snapshot):
        nombre_archivo, sha = original_paso2(storage_, year, month, snapshot)
        ruta = f"cierres/{nombre_archivo}"
        # Fuerza una discrepancia: el contenido publicado ya no corresponde
        # al SHA-256 calculado antes de subirlo (simula una subida corrupta).
        storage_.archive_files[ruta] = storage_.archive_files[ruta] + b"\x00\x00corrupcion"
        return nombre_archivo, sha

    monkeypatch.setattr(monthly_close, "_paso2_publicar", publicar_y_corromper)

    ventas_antes = storage.read_sheet(schema.VENTAS).copy()
    movimientos_antes = storage.read_sheet(schema.MOVIMIENTOS).copy()

    with pytest.raises(monthly_close.CierreVerificacionError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 6)

    assert storage.get_config("ultimo_mes_cerrado") is None
    pd.testing.assert_frame_equal(storage.read_sheet(schema.VENTAS), ventas_antes)
    pd.testing.assert_frame_equal(storage.read_sheet(schema.MOVIMIENTOS), movimientos_antes)


# ------------------------------------------------ caídas simuladas + retoma


def test_caida_simulada_justo_despues_del_paso1_reejecucion_converge(storage, monkeypatch):
    _poblar_junio_2020(storage)
    original = monthly_close._paso2_publicar
    estado = {"llamadas": 0}

    def falla_la_primera_vez(*args, **kwargs):
        estado["llamadas"] += 1
        if estado["llamadas"] == 1:
            raise RuntimeError("caida simulada: justo despues de construir el snapshot (paso 1)")
        return original(*args, **kwargs)

    monkeypatch.setattr(monthly_close, "_paso2_publicar", falla_la_primera_vez)
    with pytest.raises(RuntimeError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    assert storage.get_config("ultimo_mes_cerrado") is None
    assert "cierres/2020-06.xlsx" not in storage.archive_files  # nada se publicó todavía

    monkeypatch.setattr(monthly_close, "_paso2_publicar", original)
    resultado = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    _assert_cierre_correcto(storage, resultado)


def test_caida_simulada_justo_despues_del_paso2_reejecucion_converge(storage, monkeypatch):
    _poblar_junio_2020(storage)
    original = monthly_close._paso3_verificar
    estado = {"llamadas": 0}

    def falla_la_primera_vez(*args, **kwargs):
        estado["llamadas"] += 1
        if estado["llamadas"] == 1:
            raise RuntimeError("caida simulada: justo despues de publicar en Archive (paso 2)")
        return original(*args, **kwargs)

    monkeypatch.setattr(monthly_close, "_paso3_verificar", falla_la_primera_vez)
    with pytest.raises(RuntimeError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    assert storage.get_config("ultimo_mes_cerrado") is None
    assert "cierres/2020-06.xlsx" in storage.archive_files  # el paso 2 SI alcanzó a publicar

    monkeypatch.setattr(monthly_close, "_paso3_verificar", original)
    resultado = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    _assert_cierre_correcto(storage, resultado)  # el reintento NO duplicó la entrada del índice


def test_caida_simulada_justo_despues_del_paso3_reejecucion_converge(storage, monkeypatch):
    _poblar_junio_2020(storage)
    original = monthly_close._paso4_aplicar
    estado = {"llamadas": 0}

    def falla_la_primera_vez(*args, **kwargs):
        estado["llamadas"] += 1
        if estado["llamadas"] == 1:
            raise RuntimeError("caida simulada: justo despues de verificar el cierre publicado (paso 3)")
        return original(*args, **kwargs)

    monkeypatch.setattr(monthly_close, "_paso4_aplicar", falla_la_primera_vez)
    with pytest.raises(RuntimeError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    assert storage.get_config("ultimo_mes_cerrado") is None
    assert len(storage.read_sheet(schema.VENTAS)) == 3  # la base viva sigue completa

    monkeypatch.setattr(monthly_close, "_paso4_aplicar", original)
    resultado = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    _assert_cierre_correcto(storage, resultado)


def test_caida_simulada_a_mitad_de_la_transaccion_del_paso4_no_deja_nada_a_medias(storage, monkeypatch):
    _poblar_junio_2020(storage)
    original_to_iso = monthly_close.to_iso_utc
    estado = {"llamadas": 0}

    def falla_la_primera_vez(dt):
        estado["llamadas"] += 1
        if estado["llamadas"] == 1:
            raise RuntimeError("caida simulada: a mitad de la transaccion del paso 4 (tras vaciar las 7 hojas)")
        return original_to_iso(dt)

    monkeypatch.setattr(monthly_close, "to_iso_utc", falla_la_primera_vez)
    with pytest.raises(RuntimeError):
        monthly_close.cerrar_mes(storage, "admin", 2020, 6)

    # R6: la transacción completa se descartó, NO solo una parte.
    assert storage.get_config("ultimo_mes_cerrado") is None
    assert len(storage.read_sheet(schema.VENTAS)) == 3
    assert len(storage.read_sheet(schema.MOVIMIENTOS)) == 7
    assert len(storage.read_sheet(schema.AUDITORIA)) == 0

    monkeypatch.setattr(monthly_close, "to_iso_utc", original_to_iso)
    resultado = monthly_close.cerrar_mes(storage, "admin", 2020, 6)
    _assert_cierre_correcto(storage, resultado)
