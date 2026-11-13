"""Edición de los datos de una venta ya confirmada (solo MAESTRO).

Se editan únicamente los datos que NO cambian dinero ni stock: cliente,
teléfono, canal, datos del envío y nota. Cambiar productos, cantidades o
montos de una venta cobrada descuadraría la caja y el kardex; para eso
están "Anular venta" (deshace todo y repone stock) y "Devolución / cambio",
que dejan rastro contable. Cada edición queda en la auditoría con los
campos cambiados (valor anterior → nuevo).
"""
from __future__ import annotations

from core import schema
from core.excel_safe import excel_safe
from core.permissions import requerir
from core.seguridad import registrar_evento
from core.timeutil import now_utc, to_iso_utc

__all__ = ["CAMPOS_EDITABLES", "editar_venta"]

# campo -> largo máximo
CAMPOS_EDITABLES: dict[str, int] = {
    "cliente_nombre": 120,
    "cliente_telefono": 30,
    "canal": 20,
    "envio_ciudad": 80,
    "envio_transportadora": 80,
    "envio_guia": 80,
    "nota": 500,
}


def _texto(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor)
    return "" if texto.lower() in ("nan", "none", "<na>") else texto


def editar_venta(storage, rol: str | None, usuario_id: str | None, venta_id: str, cambios: dict) -> list[str]:
    """Aplica `cambios` (solo campos de `CAMPOS_EDITABLES`) a la venta.
    Devuelve los campos que realmente cambiaron. Una venta anulada no se
    edita (quedó cerrada con su motivo)."""
    requerir(rol, "editar_venta")
    desconocidos = set(cambios) - set(CAMPOS_EDITABLES)
    if desconocidos:
        raise ValueError(f"Estos campos no se pueden editar: {', '.join(sorted(desconocidos))}.")
    if "canal" in cambios and cambios["canal"] not in schema.CANALES_VENTA:
        raise ValueError("Canal inválido.")

    with storage.transaction() as tx:
        ventas = tx.read_sheet(schema.VENTAS)
        coincide = ventas["id"] == venta_id
        if not coincide.any():
            raise ValueError(f"La venta '{venta_id}' no existe.")
        venta = ventas[coincide].iloc[0]
        if str(venta["estado"]) == "anulada":
            raise ValueError("Una venta anulada no se puede editar.")
        cambiados: list[str] = []
        detalle: list[str] = []
        for campo, valor in cambios.items():
            nuevo = excel_safe(_texto(valor).strip(), max_length=CAMPOS_EDITABLES[campo], field_name=campo)
            anterior = _texto(venta[campo])
            if nuevo != anterior:
                ventas[campo] = ventas[campo].astype(object)
                ventas.loc[coincide, campo] = nuevo
                cambiados.append(campo)
                detalle.append(f"{campo}: '{anterior[:40]}' -> '{nuevo[:40]}'")
        if not cambiados:
            return []
        ventas.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
        tx.write_sheet(schema.VENTAS, ventas)
        registrar_evento(tx, usuario_id, "editar_venta", f"venta={venta['numero']} " + "; ".join(detalle))
    return cambiados
