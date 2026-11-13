"""Permisos por rol, revalidados DENTRO de cada función de dominio (§10).

CONTRATO CONGELADO — ver docs/CONTRATOS.md. No ocultar un botón en la UI
no es suficiente: toda función de core/ que ejecute una acción sensible
debe llamar a `requerir(rol, "capacidad")` como primera línea.

Conjunto inicial de capacidades (§4, §6, §10). Si un módulo de dominio
necesita una capacidad nueva, debe pedirla en su informe final en vez de
editar este archivo.
"""
from __future__ import annotations

ADMIN = "admin"
VENDEDOR = "vendedor"
# Maestro: el dueño del sistema (uno solo). Todo lo del administrador y del
# vendedor, más editar usuarios (nombre, usuario, rol), editar los datos de
# una venta y crear/eliminar datos de prueba. Ningún administrador puede
# desactivarlo ni restablecer su clave.
MAESTRO = "maestro"

CAPABILITIES: dict[str, frozenset[str]] = {
    ADMIN: frozenset(
        {
            "vender",
            "ver_ventas_todas",
            "anular_venta",
            "devolucion_cambio",
            "ver_costos",
            "ver_analisis_basico",
            "ver_analisis_completo",
            "gestionar_inventario",
            "ajustar_stock",
            "importar_inventario",
            "etiquetas",
            "verificar_integridad",
            "cuadre_caja",
            "cerrar_mes",
            "gestionar_usuarios",
            "resolver_conflicto_sync",
            "descargar_respaldo",
            "configurar_negocio",
        }
    ),
    VENDEDOR: frozenset(
        {
            "vender",
            "ver_ventas_propias",
            "devolucion_cambio",
            "cuadre_caja",
            "ver_analisis_basico",
        }
    ),
}

__all__ = [
    "ADMIN",
    "VENDEDOR",
    "MAESTRO",
    "ROLES_ADMINISTRATIVOS",
    "nombre_rol",
    "CAPABILITIES",
    "PermisoDenegadoError",
    "tiene_capacidad",
    "requerir",
]


class PermisoDenegadoError(PermissionError):
    def __init__(self, rol: str, capacidad: str) -> None:
        self.rol = rol
        self.capacidad = capacidad
        super().__init__(f"El rol '{rol}' no tiene la capacidad '{capacidad}'.")


def tiene_capacidad(rol: str, capacidad: str) -> bool:
    return capacidad in CAPABILITIES.get(rol, frozenset())


def requerir(rol: str, capacidad: str) -> None:
    """Lanza `PermisoDenegadoError` si el rol no tiene la capacidad.

    Debe llamarse al INICIO de cada función de dominio sensible en
    core/ — no basta con ocultar el control en la pantalla.
    """
    if not tiene_capacidad(rol, capacidad):
        raise PermisoDenegadoError(rol, capacidad)


# Maestro = TODO lo del administrador y del vendedor (calculado, así nunca
# se queda atrás si se agrega una capacidad nueva) + sus exclusivas.
CAPACIDADES_EXCLUSIVAS_MAESTRO = frozenset(
    {"editar_usuarios", "editar_venta", "datos_prueba", "iniciar_produccion"}
)
CAPABILITIES[MAESTRO] = CAPABILITIES[ADMIN] | CAPABILITIES[VENDEDOR] | CAPACIDADES_EXCLUSIVAS_MAESTRO

# Roles que cuentan como "administrador" (p.ej. para no dejar el negocio sin
# uno activo).
ROLES_ADMINISTRATIVOS = frozenset({ADMIN, MAESTRO})

_NOMBRES_ROL = {MAESTRO: "Maestro", ADMIN: "Administrador", VENDEDOR: "Vendedor"}


def nombre_rol(rol: str) -> str:
    """Nombre del rol para mostrar en pantalla."""
    return _NOMBRES_ROL.get(rol, str(rol).capitalize())
