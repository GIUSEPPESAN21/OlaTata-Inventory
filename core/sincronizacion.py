"""Acciones de sincronización con la base en la nube (OlaTata-Database).

Envoltorio de dominio sobre `core.storage.Storage` para que la vista de
Ajustes nunca llame a operaciones sensibles sin revalidar el permiso
(§10, CLAUDE.md regla 4): cada función exige `resolver_conflicto_sync`
como primera línea. Sin Streamlit: 100% testeable con un `Storage` real
y `requests` simulado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.permissions import requerir

__all__ = [
    "OPCION_USAR_NUBE",
    "OPCION_CONSERVAR_LOCAL",
    "EstadoConexion",
    "estado_conexion",
    "sincronizar_ahora",
    "resolver_conflicto",
]

OPCION_USAR_NUBE = "nube"
OPCION_CONSERVAR_LOCAL = "local"


@dataclass(frozen=True)
class EstadoConexion:
    """Resumen legible de cómo está conectada la app a la base."""

    modo: str  # "nube" | "local"
    repositorio: str | None
    archivo: str
    sha_remoto: str | None


def estado_conexion(storage: Any) -> EstadoConexion:
    """Sin permiso especial: es solo informativo (no expone el token)."""
    sync = bool(getattr(storage, "sync_enabled", False))
    sha = getattr(storage, "_known_remote_sha", None) or getattr(storage, "sha_remoto_cargado", None)
    return EstadoConexion(
        modo="nube" if sync else "local",
        repositorio=getattr(storage, "github_repo", None) if sync else None,
        archivo=str(getattr(storage, "local_path", "")),
        sha_remoto=sha,
    )


def sincronizar_ahora(storage: Any, rol: str | None) -> Any:
    """Reintenta publicar cambios pendientes. Devuelve el `SyncStatus`."""
    requerir(rol, "resolver_conflicto_sync")
    return storage.sincronizar_ahora()


def resolver_conflicto(storage: Any, rol: str | None, opcion: str) -> Any:
    """Aplica de verdad la versión elegida (antes solo se "dejaba
    constancia" en texto). `opcion` en {OPCION_USAR_NUBE,
    OPCION_CONSERVAR_LOCAL}. Ninguna de las dos borra datos: la nube
    conserva su historial de commits y la copia local se respalda."""
    requerir(rol, "resolver_conflicto_sync")
    if opcion == OPCION_USAR_NUBE:
        return storage.resolver_conflicto_usar_nube()
    if opcion == OPCION_CONSERVAR_LOCAL:
        return storage.resolver_conflicto_conservar_local()
    raise ValueError(f"Opción de resolución inválida: {opcion!r}")
