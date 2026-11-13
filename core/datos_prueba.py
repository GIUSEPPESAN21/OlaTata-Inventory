"""Datos de prueba para ensayar la app con la base REAL, y su limpieza.

Crea (solo el MAESTRO):
- 2 usuarios: `prueba.admin` (administrador) y `prueba.vendedor` (vendedor),
  con claves aleatorias que se muestran UNA vez (nunca en el código: el
  repositorio de código es público).
- 1 producto: "[PRUEBA] Bolso de prueba" con 10 unidades.
- 1 venta simulada de 2 unidades, hecha por `prueba.vendedor` con las
  MISMAS funciones de una venta real (stock, kardex, pagos, numeración).

`eliminar_datos_prueba` borra todo eso en una sola transacción atómica
(usuarios, producto, su stock y movimientos, la venta con sus ítems,
pagos y devoluciones, y cuadres de caja de los usuarios de prueba), de
modo que el invariante stock = Σ movimientos se mantiene y las cifras
de Análisis vuelven a ser solo las reales. La auditoría NO se borra:
queda constancia de que hubo datos de prueba.
"""
from __future__ import annotations

import uuid

from core import auth, inventory, schema
from core.permissions import ADMIN, VENDEDOR, requerir
from core.sales import confirmar_venta
from core.seguridad import generar_password_temporal, registrar_evento

__all__ = [
    "USUARIOS_PRUEBA",
    "PREFIJO_PRODUCTO",
    "hay_datos_prueba",
    "crear_datos_prueba",
    "eliminar_datos_prueba",
]

USUARIOS_PRUEBA = {
    "prueba.admin": ("Administrador de prueba", ADMIN),
    "prueba.vendedor": ("Vendedor de prueba", VENDEDOR),
}
PREFIJO_PRODUCTO = "[PRUEBA]"
_PRODUCTO = {"nombre": f"{PREFIJO_PRODUCTO} Bolso de prueba", "categoria": "Bolsos", "costo": 45000, "precio": 98000}


def _ids_usuarios_prueba(storage) -> set[str]:
    df = storage.read_sheet(schema.USUARIOS)
    return set(df.loc[df["usuario"].isin(USUARIOS_PRUEBA), "id"].astype(str))


def _ids_productos_prueba(storage) -> set[str]:
    df = storage.read_sheet(schema.PRODUCTOS)
    return set(df.loc[df["nombre"].astype(str).str.startswith(PREFIJO_PRODUCTO), "id"].astype(str))


def hay_datos_prueba(storage) -> bool:
    return bool(_ids_usuarios_prueba(storage) or _ids_productos_prueba(storage))


def crear_datos_prueba(storage, rol: str | None, usuario_id: str | None) -> dict:
    """Devuelve `{"usuarios": {usuario: clave}, "producto_id": ..., "venta_numero": ...}`."""
    requerir(rol, "datos_prueba")
    if hay_datos_prueba(storage):
        raise ValueError("Ya existen datos de prueba. Elimínalos primero si quieres crearlos de nuevo.")

    claves: dict[str, str] = {}
    ids: dict[str, str] = {}
    with storage.transaction() as tx:
        for usuario, (nombre, rol_prueba) in USUARIOS_PRUEBA.items():
            clave = generar_password_temporal()
            ids[usuario] = auth.crear_usuario(
                tx, nombre=nombre, usuario=usuario, password_plano=clave, rol=rol_prueba,
                must_change_password=False, rol_llamador=rol,
            )
            claves[usuario] = clave
        registrar_evento(tx, usuario_id, "crear_datos_prueba", "usuarios=prueba.admin,prueba.vendedor")

    producto = inventory.crear_producto(
        storage, rol, nombre=_PRODUCTO["nombre"], usuario_id=usuario_id or "", categoria=_PRODUCTO["categoria"],
        costo=_PRODUCTO["costo"], precio=_PRODUCTO["precio"], stock_minimo=2, stock_inicial=10,
    )
    venta = confirmar_venta(
        storage,
        VENDEDOR,
        f"prueba-{uuid.uuid4()}",
        items=[{
            "producto_id": producto["id"], "cantidad": 2, "precio_unitario": _PRODUCTO["precio"],
            "costo_unitario": _PRODUCTO["costo"], "nombre_snapshot": _PRODUCTO["nombre"],
        }],
        pagos=[{"metodo": "efectivo", "monto": 2 * _PRODUCTO["precio"]}],
        canal="tienda",
        cliente={"nombre": "Cliente de prueba", "telefono": "3000000000"},
        vendedor_id=ids["prueba.vendedor"],
        vendedor_nombre=USUARIOS_PRUEBA["prueba.vendedor"][0],
        nota="Venta simulada (datos de prueba)",
    )
    return {"usuarios": claves, "producto_id": producto["id"], "venta_numero": venta.numero}


def eliminar_datos_prueba(storage, rol: str | None, usuario_id: str | None) -> dict:
    """Borra los datos de prueba. Devuelve cuántas filas se quitaron por hoja."""
    requerir(rol, "datos_prueba")
    with storage.transaction() as tx:
        usuarios_p = _ids_usuarios_prueba(tx)
        productos_p = _ids_productos_prueba(tx)
        ventas = tx.read_sheet(schema.VENTAS)
        items = tx.read_sheet(schema.VENTA_ITEMS)

        ventas_con_producto = set(items.loc[items["producto_id"].astype(str).isin(productos_p), "venta_id"].astype(str))
        ventas_p = ventas_con_producto | set(ventas.loc[ventas["vendedor_id"].astype(str).isin(usuarios_p), "id"].astype(str))
        # Nunca borrar una venta REAL que por error incluya el producto de prueba.
        reales = items[items["venta_id"].astype(str).isin(ventas_p) & ~items["producto_id"].astype(str).isin(productos_p)]
        if not reales.empty:
            raise ValueError(
                "Hay ventas con productos reales mezcladas con datos de prueba. "
                "Anúlalas desde Ventas y vuelve a intentar."
            )
        numeros_p = set(ventas.loc[ventas["id"].astype(str).isin(ventas_p), "numero"].astype(str))
        devoluciones = tx.read_sheet(schema.DEVOLUCIONES)
        devoluciones_p = set(devoluciones.loc[devoluciones["venta_numero"].astype(str).isin(numeros_p), "id"].astype(str))

        filtros = {
            schema.VENTAS: ("id", ventas_p),
            schema.VENTA_ITEMS: ("venta_id", ventas_p),
            schema.PAGOS: ("venta_id", ventas_p),
            schema.DEVOLUCIONES: ("id", devoluciones_p),
            schema.DEVOLUCION_ITEMS: ("devolucion_id", devoluciones_p),
            schema.MOVIMIENTOS: ("producto_id", productos_p),
            schema.STOCK: ("producto_id", productos_p),
            schema.PRODUCTOS: ("id", productos_p),
            schema.CUADRE_CAJA: ("usuario_id", usuarios_p),
            schema.USUARIOS: ("id", usuarios_p),
        }
        quitadas: dict[str, int] = {}
        for hoja, (columna, valores) in filtros.items():
            df = tx.read_sheet(hoja)
            borrar = df[columna].astype(str).isin(valores)
            if borrar.any():
                tx.write_sheet(hoja, df[~borrar])
            quitadas[hoja] = int(borrar.sum())
        registrar_evento(
            tx, usuario_id, "eliminar_datos_prueba",
            ", ".join(f"{h}={n}" for h, n in quitadas.items() if n),
        )
    return quitadas
