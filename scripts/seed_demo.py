"""Generador de datos de demostración 100% FICTICIOS, con semilla fija.

Propiedad de A6 (QA y Datos). Usa SOLO la API pública de `core/`:
`storage.transaction()`, `core.auth.crear_usuario`, y escritura directa de
hojas con `write_sheet` para ventas/movimientos ficticios, porque
`core.sales`/`core.inventory` (propiedad de A1-A2) AÚN NO EXISTEN en esta
rama. Ningún dato real: nombres, teléfonos y catálogo son inventados.

Uso como librería (lo que usan `scripts/smoke_e2e.py` y las pruebas):

    from scripts.seed_demo import crear_usuarios_demo, crear_catalogo_y_proveedores, generar_ventas_dia

Uso como script (crea un libro de demostración en disco para explorar):

    python scripts/seed_demo.py --output OLATATA_DB_DEMO.xlsx --dias 90 --ventas-por-dia 40
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.excel_safe import excel_safe  # noqa: E402
from core.timeutil import BOGOTA, UTC, now_utc, to_iso_utc  # noqa: E402

SEED_POR_DEFECTO = 42
SEDE = schema.SEDE_PRINCIPAL

# Catálogo ficticio fijo (bolsos y accesorios) — nunca datos reales.
CATALOGO_BASE: list[dict] = [
    {"nombre": "Bolso tote clásico", "categoria": "Bolsos", "color": "Negro", "costo": 45000, "precio": 89000},
    {"nombre": "Bolso tote clásico", "categoria": "Bolsos", "color": "Café", "costo": 45000, "precio": 89000},
    {"nombre": "Bolso cruzado mini", "categoria": "Bolsos", "color": "Rosado", "costo": 32000, "precio": 65000},
    {"nombre": "Bolso cruzado mini", "categoria": "Bolsos", "color": "Beige", "costo": 32000, "precio": 65000},
    {"nombre": "Morral urbano", "categoria": "Mochilas", "color": "Negro", "costo": 52000, "precio": 99000},
    {"nombre": "Morral urbano", "categoria": "Mochilas", "color": "Azul", "costo": 52000, "precio": 99000},
    {"nombre": "Mochila mini dama", "categoria": "Mochilas", "color": "Rojo", "costo": 38000, "precio": 72000},
    {"nombre": "Billetera dama", "categoria": "Billeteras", "color": "Café", "costo": 18000, "precio": 39000},
    {"nombre": "Billetera dama", "categoria": "Billeteras", "color": "Negro", "costo": 18000, "precio": 39000},
    {"nombre": "Billetera caballero", "categoria": "Billeteras", "color": "Negro", "costo": 20000, "precio": 42000},
    {"nombre": "Monedero", "categoria": "Billeteras", "color": "Dorado", "costo": 9000, "precio": 22000},
    {"nombre": "Cartuchera", "categoria": "Accesorios", "color": "Verde", "costo": 7000, "precio": 18000},
    {"nombre": "Cosmetiquera", "categoria": "Accesorios", "color": "Rosado", "costo": 8000, "precio": 20000},
    {"nombre": "Bolso de playa", "categoria": "Bolsos", "color": "Blanco", "costo": 25000, "precio": 55000},
    {"nombre": "Maleta de viaje pequeña", "categoria": "Mochilas", "color": "Plateado", "costo": 95000, "precio": 180000},
    {"nombre": "Riñonera", "categoria": "Accesorios", "color": "Negro", "costo": 15000, "precio": 32000},
    {"nombre": "Bolso de hombro", "categoria": "Bolsos", "color": "Café", "costo": 40000, "precio": 82000},
    {"nombre": "Bolso de hombro", "categoria": "Bolsos", "color": "Beige", "costo": 40000, "precio": 82000},
    {"nombre": "Correa para bolso", "categoria": "Accesorios", "color": "Dorado", "costo": 10000, "precio": 25000},
    {"nombre": "Llavero decorativo", "categoria": "Accesorios", "color": "Rosado", "costo": 4000, "precio": 12000},
    {"nombre": "Maletín ejecutivo", "categoria": "Bolsos", "color": "Negro", "costo": 70000, "precio": 140000},
    {"nombre": "Cangurera", "categoria": "Accesorios", "color": "Azul", "costo": 16000, "precio": 34000},
    {"nombre": "Bolso tejido", "categoria": "Bolsos", "color": "Beige", "costo": 28000, "precio": 58000},
    {"nombre": "Portadocumentos", "categoria": "Accesorios", "color": "Negro", "costo": 22000, "precio": 45000},
]

PROVEEDORES_BASE: list[dict] = [
    {"nombre": "Distribuidora Ficticia Buga", "telefono": "3000000001", "ciudad": "Buga"},
    {"nombre": "Importadora Ejemplo Tuluá", "telefono": "3000000002", "ciudad": "Tuluá"},
    {"nombre": "Talleres Demo Cali", "telefono": "3000000003", "ciudad": "Cali"},
]

NOMBRES_CLIENTE_FICTICIOS = [
    "Cliente mostrador", "Cliente Instagram", "Cliente WhatsApp", "Cliente frecuente",
    "Cliente nuevo", "Cliente mayorista",
]

MOTIVOS_DEVOLUCION = ["Talla equivocada", "No le gustó el color", "Producto con defecto", "Cambio de opinión"]


def _texto(valor: object) -> str:
    return excel_safe(valor)


def _nuevo_id(tx, contador: str, prefijo: str, ancho: int = 6) -> str:
    return f"{prefijo}-{tx.next_counter(contador):0{ancho}d}"


class _RelojDelDia:
    """Genera horas DENTRO del día, aleatorias en su espaciado pero
    SIEMPRE crecientes entre llamadas sucesivas (con una cola deliberada
    hasta las 23:45 Bogotá para ejercitar el defecto §2a si se
    reintrodujera). Es clave que crezcan: el orden en que este script
    procesa ventas/devoluciones ya respeta la cadena stock_antes/
    stock_despues por producto, y esa cadena solo es coherente con
    `fecha_hora_utc` si las horas asignadas avanzan en el mismo orden en
    que se procesan — igual que en producción real, donde el reloj del
    servidor nunca retrocede entre una venta y la siguiente. Horas
    independientes y no ordenadas (lo que hacía la versión anterior de
    este generador) rompían esa cadena y producían un libro vivo
    inconsistente tras el cierre de mes."""

    def __init__(self, rng: random.Random, fecha_local: date) -> None:
        self._rng = rng
        self._fecha_local = fecha_local
        self._minuto = 9 * 60  # arranca a las 9:00am Bogotá

    def siguiente(self) -> datetime:
        self._minuto = min(self._minuto + self._rng.randint(1, 6), 23 * 60 + 45)
        hora, minuto = divmod(self._minuto, 60)
        dt_local = datetime(
            self._fecha_local.year, self._fecha_local.month, self._fecha_local.day, hora, minuto, 0, tzinfo=BOGOTA
        )
        return dt_local.astimezone(UTC)


def crear_usuarios_demo(storage) -> dict[str, str]:
    """Crea un admin y una vendedora ficticios. Devuelve {"admin": id, "vendedor": id}."""
    from core.auth import crear_usuario
    from core.permissions import ADMIN, VENDEDOR

    ids: dict[str, str] = {}
    with storage.transaction() as tx:
        ids["admin"] = crear_usuario(
            tx, nombre="Admin Demo", usuario="admin.demo", password_plano="Demo-12345", rol=ADMIN,
            must_change_password=False,
        )
        ids["vendedor"] = crear_usuario(
            tx, nombre="Vendedora Demo", usuario="vendedora.demo", password_plano="Demo-12345", rol=VENDEDOR,
            must_change_password=False,
        )
    return ids


def crear_catalogo_y_proveedores(storage, rng: random.Random, fecha_referencia: date | None = None) -> list[dict]:
    """Crea proveedores, productos y su stock inicial (con el movimiento
    `stock_inicial` correspondiente). Devuelve una lista de dicts mutables
    `{"id", "nombre", "costo", "precio", "stock"}` que el resto del seed usa
    como caché de trabajo (y que se mantiene sincronizada con la hoja STOCK
    real dentro de cada transacción posterior).

    `fecha_referencia`: si se da, el movimiento `stock_inicial` se fecha a
    las 00:00 Bogotá de ese día en vez de "ahora" (reloj real). Importante
    para simulaciones históricas (smoke E2E): si se deja en `now_utc()` y
    la simulación finge ocurrir en el pasado (p.ej. 2025), ese movimiento
    queda fuera del rango de TODOS los cierres de mes simulados y nunca se
    archiva — rompiendo el invariante "stock = Σ movimientos" del libro
    vivo para siempre. Con `fecha_referencia` queda dentro del primer mes
    simulado y se archiva normalmente en su cierre."""
    if fecha_referencia is not None:
        ahora = to_iso_utc(datetime(fecha_referencia.year, fecha_referencia.month, fecha_referencia.day, tzinfo=BOGOTA))
    else:
        ahora = to_iso_utc(now_utc())
    productos: list[dict] = []
    with storage.transaction() as tx:
        df_prov = tx.read_sheet(schema.PROVEEDORES)
        filas_prov = []
        for base in PROVEEDORES_BASE:
            pid = _nuevo_id(tx, "proveedores", "PR")
            filas_prov.append(
                {
                    "id": pid,
                    "nombre": _texto(base["nombre"]),
                    "telefono": _texto(base["telefono"]),
                    "ciudad": _texto(base["ciudad"]),
                    "notas": "",
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
        tx.write_sheet(schema.PROVEEDORES, pd.concat([df_prov, pd.DataFrame(filas_prov)], ignore_index=True))
        proveedor_ids = [f["id"] for f in filas_prov]

        df_prod = tx.read_sheet(schema.PRODUCTOS)
        df_stock = tx.read_sheet(schema.STOCK)
        df_mov = tx.read_sheet(schema.MOVIMIENTOS)
        filas_prod, filas_stock, filas_mov = [], [], []
        for base in CATALOGO_BASE:
            prod_id = _nuevo_id(tx, "productos", "P")
            stock_inicial = rng.randint(15, 60)
            proveedor_id = rng.choice(proveedor_ids)
            filas_prod.append(
                {
                    "id": prod_id,
                    "nombre": _texto(base["nombre"]),
                    "categoria": _texto(base["categoria"]),
                    "color": _texto(base["color"]),
                    "talla_tamano": "",
                    "proveedor_id": proveedor_id,
                    "costo": base["costo"],
                    "precio": base["precio"],
                    "stock_minimo": 3,
                    "codigo_barras": f"770{prod_id[2:]}00",
                    "activo": True,
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
            filas_stock.append(
                {
                    "producto_id": prod_id,
                    "sede_id": SEDE,
                    "cantidad": stock_inicial,
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
            mov_id = _nuevo_id(tx, "movimientos", "M", 7)
            filas_mov.append(
                {
                    "id": mov_id,
                    "fecha_hora_utc": ahora,
                    "producto_id": prod_id,
                    "sede_id": SEDE,
                    "tipo": "stock_inicial",
                    "cantidad": stock_inicial,
                    "stock_antes": 0,
                    "stock_despues": stock_inicial,
                    "costo_unitario": base["costo"],
                    "ref_tipo": "",
                    "ref_id": "",
                    "proveedor_id": proveedor_id,
                    "documento_ref": "",
                    "usuario_id": "",
                    "nota": "Carga inicial demo (ficticia)",
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
            productos.append(
                {"id": prod_id, "nombre": base["nombre"], "costo": base["costo"], "precio": base["precio"], "stock": stock_inicial}
            )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([df_prod, pd.DataFrame(filas_prod)], ignore_index=True))
        tx.write_sheet(schema.STOCK, pd.concat([df_stock, pd.DataFrame(filas_stock)], ignore_index=True))
        tx.write_sheet(schema.MOVIMIENTOS, pd.concat([df_mov, pd.DataFrame(filas_mov)], ignore_index=True))
    return productos


def _actualizar_stock_sheet(tx, productos_tocados: dict[str, int]) -> None:
    ahora = to_iso_utc(now_utc())
    df_stock = tx.read_sheet(schema.STOCK)
    for prod_id, nueva_cantidad in productos_tocados.items():
        coincide = (df_stock["producto_id"] == prod_id) & (df_stock["sede_id"] == SEDE)
        df_stock.loc[coincide, "cantidad"] = nueva_cantidad
        df_stock.loc[coincide, "updated_at"] = ahora
    tx.write_sheet(schema.STOCK, df_stock)


def generar_ventas_dia(
    storage,
    rng: random.Random,
    fecha_local: date,
    productos: list[dict],
    usuarios: dict[str, str],
    historial_vendido: list[dict],
    ventas_por_dia: int = 40,
    pct_devolucion: float = 0.05,
) -> dict:
    """Genera las ventas (y algunas devoluciones) de UN día, dentro de UNA
    sola `transaction()` (simula el cuadre de caja diario). Todas las
    cantidades de dinero son `int` (COP, R1); las horas se generan en
    America/Bogota y se guardan en ISO-8601 UTC (R2).

    Devuelve un resumen con los totales del día, útil para que el llamador
    (smoke_e2e) verifique los invariantes sin tener que releer el libro.
    """
    mes_key = f"{fecha_local.year:04d}-{fecha_local.month:02d}"
    resumen = {
        "fecha_local": fecha_local.isoformat(),
        "ventas": 0,
        "items": 0,
        "total_vendido": 0,
        "total_pagado": 0,
        "devoluciones": 0,
        "total_reembolsado": 0,
    }
    vendedores = [
        (usuarios["admin"], "Admin Demo"),
        (usuarios["vendedor"], "Vendedora Demo"),
    ]
    productos_tocados: dict[str, int] = {}

    with storage.transaction() as tx:
        df_ventas = tx.read_sheet(schema.VENTAS)
        df_items = tx.read_sheet(schema.VENTA_ITEMS)
        df_pagos = tx.read_sheet(schema.PAGOS)
        df_mov = tx.read_sheet(schema.MOVIMIENTOS)
        df_dev = tx.read_sheet(schema.DEVOLUCIONES)
        df_dev_items = tx.read_sheet(schema.DEVOLUCION_ITEMS)

        nuevas_ventas, nuevos_items, nuevos_pagos, nuevos_mov = [], [], [], []
        nuevas_dev, nuevos_dev_items = [], []
        reloj = _RelojDelDia(rng, fecha_local)

        for _ in range(ventas_por_dia):
            disponibles = [p for p in productos if p["stock"] > 0]
            if not disponibles:
                break
            dt_utc = reloj.siguiente()
            ahora = to_iso_utc(dt_utc)
            n_lineas = rng.choice([1, 1, 1, 2, 2, 3])
            elegidos = rng.sample(disponibles, k=min(n_lineas, len(disponibles)))
            venta_id = _nuevo_id(tx, "ventas_id", "V", 7)
            numero = tx.next_counter("ventas_numero", reset_key=mes_key)
            vendedor_id, vendedor_nombre = rng.choice(vendedores)

            subtotal = 0
            descuento_total = 0
            for prod in elegidos:
                cantidad = rng.randint(1, min(3, prod["stock"]))
                precio_unitario = prod["precio"]
                descuento_linea = 0
                if rng.random() < 0.12:
                    descuento_linea = min(precio_unitario * cantidad, rng.choice([2000, 5000, 10000]))
                total_linea = precio_unitario * cantidad - descuento_linea
                subtotal += precio_unitario * cantidad
                descuento_total += descuento_linea

                item_id = _nuevo_id(tx, "venta_items", "VI", 7)
                nuevos_items.append(
                    {
                        "id": item_id,
                        "venta_id": venta_id,
                        "producto_id": prod["id"],
                        "nombre_snapshot": _texto(prod["nombre"]),
                        "cantidad": cantidad,
                        "precio_unitario": precio_unitario,
                        "descuento_linea": descuento_linea,
                        "costo_unitario": prod["costo"],
                        "total_linea": total_linea,
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )

                stock_antes = prod["stock"]
                prod["stock"] -= cantidad
                productos_tocados[prod["id"]] = prod["stock"]
                mov_id = _nuevo_id(tx, "movimientos", "M", 7)
                nuevos_mov.append(
                    {
                        "id": mov_id,
                        "fecha_hora_utc": ahora,
                        "producto_id": prod["id"],
                        "sede_id": SEDE,
                        "tipo": "venta",
                        "cantidad": -cantidad,
                        "stock_antes": stock_antes,
                        "stock_despues": prod["stock"],
                        "costo_unitario": prod["costo"],
                        "ref_tipo": "venta",
                        "ref_id": venta_id,
                        "proveedor_id": "",
                        "documento_ref": "",
                        "usuario_id": vendedor_id,
                        "nota": "",
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )
                historial_vendido.append(
                    {
                        "venta_id": venta_id,
                        "venta_numero": numero,
                        "producto_id": prod["id"],
                        "nombre": prod["nombre"],
                        "cantidad_disponible": cantidad,
                        "precio_unitario": precio_unitario,
                        "costo_unitario": prod["costo"],
                    }
                )

            envio = rng.choice([0, 0, 0, 0, 8000, 12000])
            canal = rng.choices(list(schema.CANALES_VENTA), weights=[0.7, 0.15, 0.15])[0]
            total = subtotal - descuento_total + envio

            nuevas_ventas.append(
                {
                    "id": venta_id,
                    "numero": f"{mes_key}-{numero:04d}",
                    "fecha_hora_utc": ahora,
                    "fecha_local": fecha_local.isoformat(),
                    "sede_id": SEDE,
                    "canal": canal,
                    "cliente_nombre": _texto(rng.choice(NOMBRES_CLIENTE_FICTICIOS)),
                    "cliente_telefono": "",
                    "subtotal": subtotal,
                    "descuento_total": descuento_total,
                    "envio_cobrado": envio,
                    "envio_ciudad": "" if envio == 0 else "Tuluá",
                    "envio_transportadora": "" if envio == 0 else "Interrapidisimo",
                    "envio_guia": "",
                    "total": total,
                    "estado": "completada",
                    "anulada_por": "",
                    "anulada_motivo": "",
                    "anulada_at": "",
                    "vendedor_id": vendedor_id,
                    "vendedor_nombre": _texto(vendedor_nombre),
                    "idempotency_key": f"demo-{venta_id}",
                    "nota": "",
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )

            # Pagos: a veces divididos entre dos métodos (venta dividida).
            metodos_posibles = [m for m in schema.METODOS_PAGO if m != "cambio"]
            if rng.random() < 0.15 and total > 0:
                parte_1 = round(total * rng.choice([0.4, 0.5, 0.6]))
                parte_2 = total - parte_1
                metodo_1, metodo_2 = rng.sample(metodos_posibles, k=2)
                for metodo, monto in ((metodo_1, parte_1), (metodo_2, parte_2)):
                    if monto <= 0:
                        continue
                    pago_id = _nuevo_id(tx, "pagos", "PG", 7)
                    nuevos_pagos.append(
                        {
                            "id": pago_id,
                            "venta_id": venta_id,
                            "metodo": metodo,
                            "monto": monto,
                            "referencia": "",
                            "fecha_hora_utc": ahora,
                            "created_at": ahora,
                            "updated_at": ahora,
                        }
                    )
            else:
                metodo = rng.choice(metodos_posibles)
                pago_id = _nuevo_id(tx, "pagos", "PG", 7)
                nuevos_pagos.append(
                    {
                        "id": pago_id,
                        "venta_id": venta_id,
                        "metodo": metodo,
                        "monto": total,
                        "referencia": "",
                        "fecha_hora_utc": ahora,
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )

            resumen["ventas"] += 1
            resumen["items"] += len(elegidos)
            resumen["total_vendido"] += total

        # Devoluciones: una fracción de lo vendido en días anteriores.
        n_devoluciones = int(round(len(historial_vendido) * pct_devolucion)) if historial_vendido else 0
        n_devoluciones = min(n_devoluciones, len(historial_vendido), max(1, ventas_por_dia // 10))
        for _ in range(n_devoluciones):
            if not historial_vendido:
                break
            idx = rng.randrange(len(historial_vendido))
            entrada = historial_vendido.pop(idx)
            dt_utc = reloj.siguiente()
            ahora = to_iso_utc(dt_utc)
            dev_id = _nuevo_id(tx, "devoluciones", "D", 7)
            dev_numero = tx.next_counter("devoluciones_numero", reset_key=mes_key)
            tipo = rng.choice(["devolucion", "cambio"])
            reembolso_metodo = "cambio" if tipo == "cambio" else rng.choice(["efectivo", "transferencia"])
            reembolso_monto = 0 if tipo == "cambio" else entrada["precio_unitario"] * entrada["cantidad_disponible"]

            nuevas_dev.append(
                {
                    "id": dev_id,
                    "numero": f"{mes_key}-DEV-{dev_numero:04d}",
                    "venta_numero": entrada["venta_numero"],
                    "fecha_hora_utc": ahora,
                    "fecha_local": fecha_local.isoformat(),
                    "tipo": tipo,
                    "motivo": _texto(rng.choice(MOTIVOS_DEVOLUCION)),
                    "reembolso_metodo": reembolso_metodo,
                    "reembolso_monto": reembolso_monto,
                    "usuario_id": rng.choice(vendedores)[0],
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
            dev_item_id = _nuevo_id(tx, "devolucion_items", "DI", 7)
            nuevos_dev_items.append(
                {
                    "id": dev_item_id,
                    "devolucion_id": dev_id,
                    "producto_id": entrada["producto_id"],
                    "nombre_snapshot": _texto(entrada["nombre"]),
                    "cantidad": entrada["cantidad_disponible"],
                    "precio_unitario": entrada["precio_unitario"],
                    "costo_unitario": entrada["costo_unitario"],
                    "destino": "reingresa_stock",
                    "created_at": ahora,
                    "updated_at": ahora,
                }
            )
            prod = next((p for p in productos if p["id"] == entrada["producto_id"]), None)
            if prod is not None:
                stock_antes = prod["stock"]
                prod["stock"] += entrada["cantidad_disponible"]
                productos_tocados[prod["id"]] = prod["stock"]
                mov_id = _nuevo_id(tx, "movimientos", "M", 7)
                nuevos_mov.append(
                    {
                        "id": mov_id,
                        "fecha_hora_utc": ahora,
                        "producto_id": prod["id"],
                        "sede_id": SEDE,
                        "tipo": "devolucion",
                        "cantidad": entrada["cantidad_disponible"],
                        "stock_antes": stock_antes,
                        "stock_despues": prod["stock"],
                        "costo_unitario": entrada["costo_unitario"],
                        "ref_tipo": "devolucion",
                        "ref_id": dev_id,
                        "proveedor_id": "",
                        "documento_ref": "",
                        "usuario_id": "",
                        "nota": "",
                        "created_at": ahora,
                        "updated_at": ahora,
                    }
                )
            resumen["devoluciones"] += 1
            resumen["total_reembolsado"] += reembolso_monto

        resumen["total_pagado"] = sum(p["monto"] for p in nuevos_pagos)

        if nuevas_ventas:
            tx.write_sheet(schema.VENTAS, pd.concat([df_ventas, pd.DataFrame(nuevas_ventas)], ignore_index=True))
        if nuevos_items:
            tx.write_sheet(schema.VENTA_ITEMS, pd.concat([df_items, pd.DataFrame(nuevos_items)], ignore_index=True))
        if nuevos_pagos:
            tx.write_sheet(schema.PAGOS, pd.concat([df_pagos, pd.DataFrame(nuevos_pagos)], ignore_index=True))
        if nuevas_dev:
            tx.write_sheet(schema.DEVOLUCIONES, pd.concat([df_dev, pd.DataFrame(nuevas_dev)], ignore_index=True))
        if nuevos_dev_items:
            tx.write_sheet(schema.DEVOLUCION_ITEMS, pd.concat([df_dev_items, pd.DataFrame(nuevos_dev_items)], ignore_index=True))
        if nuevos_mov:
            tx.write_sheet(schema.MOVIMIENTOS, pd.concat([df_mov, pd.DataFrame(nuevos_mov)], ignore_index=True))
        if productos_tocados:
            _actualizar_stock_sheet(tx, productos_tocados)

    return resumen


def poblar_demo(storage, dias: int = 90, ventas_por_dia: int = 40, seed: int = SEED_POR_DEFECTO, fecha_inicio: date | None = None) -> dict:
    """Orquesta la generación completa: usuarios, catálogo y `dias` días de
    ventas/devoluciones. NO hace cierres de mes (eso lo orquesta
    `scripts/smoke_e2e.py`, que necesita intercalarlos entre días)."""
    rng = random.Random(seed)
    if fecha_inicio is None:
        fecha_inicio = date(2025, 9, 1)

    usuarios = crear_usuarios_demo(storage)
    productos = crear_catalogo_y_proveedores(storage, rng, fecha_referencia=fecha_inicio)

    historial_vendido: list[dict] = []
    resumenes_por_dia = []
    for offset in range(dias):
        fecha = fecha_inicio + timedelta(days=offset)
        resumen = generar_ventas_dia(
            storage, rng, fecha, productos, usuarios, historial_vendido, ventas_por_dia=ventas_por_dia
        )
        resumenes_por_dia.append(resumen)

    return {
        "usuarios": usuarios,
        "productos_finales": productos,
        "dias_generados": len(resumenes_por_dia),
        "resumenes_por_dia": resumenes_por_dia,
        "total_ventas": sum(r["ventas"] for r in resumenes_por_dia),
        "total_vendido": sum(r["total_vendido"] for r in resumenes_por_dia),
        "total_pagado": sum(r["total_pagado"] for r in resumenes_por_dia),
        "total_devoluciones": sum(r["devoluciones"] for r in resumenes_por_dia),
        "total_reembolsado": sum(r["total_reembolsado"] for r in resumenes_por_dia),
    }


def _construir_storage_real(output: Path):
    from core.storage import Storage

    return Storage(local_path=output, sync_enabled=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera un libro de demostración 100% ficticio para Ola Tata.")
    parser.add_argument("--output", default="OLATATA_DB_DEMO.xlsx", help="Ruta del .xlsx de salida.")
    parser.add_argument("--dias", type=int, default=90)
    parser.add_argument("--ventas-por-dia", type=int, default=40)
    parser.add_argument("--seed", type=int, default=SEED_POR_DEFECTO)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    storage = _construir_storage_real(Path(args.output))
    resultado = poblar_demo(storage, dias=args.dias, ventas_por_dia=args.ventas_por_dia, seed=args.seed)
    resumen_compacto = {
        "dias_generados": resultado["dias_generados"],
        "total_ventas": resultado["total_ventas"],
        "total_vendido": resultado["total_vendido"],
        "total_pagado": resultado["total_pagado"],
        "total_devoluciones": resultado["total_devoluciones"],
        "total_reembolsado": resultado["total_reembolsado"],
        "archivo": str(Path(args.output).resolve()),
    }
    print(json.dumps(resumen_compacto, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
