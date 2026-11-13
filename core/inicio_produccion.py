""""Empezar con el inventario real": limpieza única de la base.

Cuando terminen de probar, el MAESTRO deja la app lista para la operación
real: se vacían productos, stock, movimientos, ventas (con ítems, pagos y
devoluciones), proveedores y cuadres de caja, y se eliminan los usuarios
de prueba. Se conservan los usuarios reales, la configuración del negocio
y el registro de seguridad (auditoría).

Solo se puede hacer UNA vez: queda marcada la fecha en CONFIG
(`produccion_iniciada`) y desde ese momento la función se niega, la
pestaña ya no ofrece el botón y tampoco se pueden crear datos de prueba.
Todo ocurre en una sola transacción (o se hace completo o no se hace), y
la versión anterior de la base queda en el historial de GitHub.
"""
from __future__ import annotations

from core import schema
from core.datos_prueba import USUARIOS_PRUEBA
from core.permissions import requerir
from core.seguridad import registrar_evento
from core.timeutil import now_utc, to_iso_utc

__all__ = ["FRASE_CONFIRMACION", "HOJAS_A_VACIAR", "produccion_iniciada", "resumen_a_borrar", "iniciar_produccion"]

FRASE_CONFIRMACION = "EMPEZAR DE CERO"

HOJAS_A_VACIAR = (
    schema.PRODUCTOS,
    schema.STOCK,
    schema.MOVIMIENTOS,
    schema.VENTAS,
    schema.VENTA_ITEMS,
    schema.PAGOS,
    schema.DEVOLUCIONES,
    schema.DEVOLUCION_ITEMS,
    schema.PROVEEDORES,
    schema.CUADRE_CAJA,
)


def produccion_iniciada(storage) -> str | None:
    """Fecha ISO (UTC) en que se empezó la operación real, o `None`."""
    return storage.get_config("produccion_iniciada")


def resumen_a_borrar(storage) -> dict[str, int]:
    """Cuántas filas se borrarían por hoja (para mostrarlo antes de confirmar)."""
    resumen = {hoja: len(storage.read_sheet(hoja)) for hoja in HOJAS_A_VACIAR}
    usuarios = storage.read_sheet(schema.USUARIOS)
    resumen["usuarios de prueba"] = int(usuarios["usuario"].isin(USUARIOS_PRUEBA).sum())
    return resumen


def iniciar_produccion(storage, rol: str | None, usuario_id: str | None, confirmacion: str) -> dict[str, int]:
    """Vacía los datos de operación conservando usuarios reales, config y
    auditoría. Exige escribir `FRASE_CONFIRMACION`. Solo una vez."""
    requerir(rol, "iniciar_produccion")
    if (confirmacion or "").strip().upper() != FRASE_CONFIRMACION:
        raise ValueError(f'Para confirmar escribe exactamente "{FRASE_CONFIRMACION}".')
    with storage.transaction() as tx:
        ya = tx.get_config("produccion_iniciada")
        if ya:
            raise ValueError(f"La limpieza para empezar con el inventario real ya se hizo ({ya[:10]}). No se repite.")
        borradas: dict[str, int] = {}
        for hoja in HOJAS_A_VACIAR:
            df = tx.read_sheet(hoja)
            borradas[hoja] = len(df)
            if len(df):
                tx.write_sheet(hoja, df.iloc[0:0])
        usuarios = tx.read_sheet(schema.USUARIOS)
        de_prueba = usuarios["usuario"].isin(USUARIOS_PRUEBA)
        borradas["usuarios de prueba"] = int(de_prueba.sum())
        if de_prueba.any():
            tx.write_sheet(schema.USUARIOS, usuarios[~de_prueba])
        if usuarios[~de_prueba].empty:
            raise ValueError("No quedaría ningún usuario real. Operación cancelada.")
        tx.set_config("produccion_iniciada", to_iso_utc(now_utc()))
        registrar_evento(
            tx, usuario_id, "iniciar_produccion",
            "Limpieza única: " + ", ".join(f"{h}={n}" for h, n in borradas.items() if n),
        )
    return borradas
