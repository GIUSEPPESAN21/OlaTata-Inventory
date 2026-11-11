"""Autenticación: bcrypt, límite de intentos con bloqueo temporal,
expiración de sesión por inactividad, cambio forzado de contraseña (§10).

CONTRATO CONGELADO — ver docs/CONTRATOS.md.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime

import bcrypt
import pandas as pd

from core import schema
from core.permissions import ADMIN, VENDEDOR
from core.timeutil import now_utc, to_iso_utc

MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 15 * 60
SESION_MINUTOS_DEFAULT = 8 * 60

__all__ = [
    "Usuario",
    "LoginResultado",
    "hash_password",
    "verify_password",
    "crear_usuario",
    "login",
    "cambiar_password",
    "validar_sesion",
]


@dataclass(frozen=True)
class Usuario:
    id: str
    nombre: str
    usuario: str
    rol: str
    activo: bool
    must_change_password: bool
    session_epoch: int


@dataclass(frozen=True)
class LoginResultado:
    ok: bool
    usuario: Usuario | None = None
    motivo: str | None = None


def hash_password(password_plano: str) -> str:
    return bcrypt.hashpw(password_plano.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(password_plano: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password_plano.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


_DUMMY_HASH = hash_password("contrasena-ficticia-para-igualar-tiempos")

_lock_attempts = threading.Lock()
_attempts: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


def _registrar_intento_fallido(usuario: str) -> None:
    with _lock_attempts:
        ahora = time.monotonic()
        historial = _attempts.setdefault(usuario, [])
        historial.append(ahora)
        historial[:] = [t for t in historial if ahora - t < BLOQUEO_SEGUNDOS]
        if len(historial) >= MAX_INTENTOS:
            _locked_until[usuario] = ahora + BLOQUEO_SEGUNDOS


def _esta_bloqueado(usuario: str) -> bool:
    with _lock_attempts:
        hasta = _locked_until.get(usuario)
        if hasta is None:
            return False
        if time.monotonic() >= hasta:
            del _locked_until[usuario]
            _attempts.pop(usuario, None)
            return False
        return True


def _limpiar_intentos(usuario: str) -> None:
    with _lock_attempts:
        _attempts.pop(usuario, None)
        _locked_until.pop(usuario, None)


def reset_intentos_para_pruebas() -> None:
    """Solo para pruebas: limpia el estado global de intentos/bloqueos."""
    with _lock_attempts:
        _attempts.clear()
        _locked_until.clear()


def _fila_a_usuario(fila: pd.Series) -> Usuario:
    return Usuario(
        id=str(fila["id"]),
        nombre=str(fila["nombre"]),
        usuario=str(fila["usuario"]),
        rol=str(fila["rol"]),
        activo=bool(fila["activo"]),
        must_change_password=bool(fila["must_change_password"]),
        session_epoch=int(fila["session_epoch"]),
    )


def login(storage, usuario: str, password: str) -> LoginResultado:
    """Verifica credenciales. Límite de intentos con bloqueo temporal,
    mensaje genérico y tiempo de respuesta equalizado (hash ficticio) para
    no filtrar si el usuario existe o no."""
    usuario = usuario.strip()
    if _esta_bloqueado(usuario):
        return LoginResultado(ok=False, motivo="Demasiados intentos. Intenta de nuevo en unos minutos.")

    df = storage.read_sheet(schema.USUARIOS)
    fila_df = df[df["usuario"] == usuario]
    if fila_df.empty:
        verify_password(password, _DUMMY_HASH)
        _registrar_intento_fallido(usuario)
        return LoginResultado(ok=False, motivo="Usuario o contraseña incorrectos.")

    fila = fila_df.iloc[0]
    if not bool(fila["activo"]):
        verify_password(password, _DUMMY_HASH)
        return LoginResultado(ok=False, motivo="Usuario o contraseña incorrectos.")

    if not verify_password(password, str(fila["password_hash"])):
        _registrar_intento_fallido(usuario)
        return LoginResultado(ok=False, motivo="Usuario o contraseña incorrectos.")

    _limpiar_intentos(usuario)
    return LoginResultado(ok=True, usuario=_fila_a_usuario(fila))


def crear_usuario(
    storage,
    *,
    nombre: str,
    usuario: str,
    password_plano: str,
    rol: str,
    must_change_password: bool = True,
) -> str:
    """Debe llamarse dentro de `storage.transaction()`. Devuelve el id creado."""
    if rol not in (ADMIN, VENDEDOR):
        raise ValueError(f"Rol inválido: {rol}")
    df = storage.read_sheet(schema.USUARIOS)
    if (df["usuario"] == usuario).any():
        raise ValueError(f"El usuario '{usuario}' ya existe.")
    nuevo_id = f"U-{storage.next_counter('usuarios'):06d}"
    ahora = to_iso_utc(now_utc())
    nueva = pd.DataFrame(
        [
            {
                "id": nuevo_id,
                "nombre": nombre,
                "usuario": usuario,
                "password_hash": hash_password(password_plano),
                "rol": rol,
                "activo": True,
                "must_change_password": must_change_password,
                "session_epoch": 1,
                "created_at": ahora,
                "updated_at": ahora,
            }
        ]
    )
    storage.write_sheet(schema.USUARIOS, pd.concat([df, nueva], ignore_index=True))
    return nuevo_id


def cambiar_password(storage, usuario_id: str, password_nuevo_plano: str) -> None:
    """Debe llamarse dentro de `storage.transaction()`. Incrementa
    `session_epoch` para revocar sesiones activas en otros dispositivos."""
    df = storage.read_sheet(schema.USUARIOS)
    coincide = df["id"] == usuario_id
    if not coincide.any():
        raise ValueError(f"Usuario '{usuario_id}' no existe.")
    ahora = to_iso_utc(now_utc())
    df.loc[coincide, "password_hash"] = hash_password(password_nuevo_plano)
    df.loc[coincide, "must_change_password"] = False
    df.loc[coincide, "session_epoch"] = df.loc[coincide, "session_epoch"].astype(int) + 1
    df.loc[coincide, "updated_at"] = ahora
    storage.write_sheet(schema.USUARIOS, df)


def validar_sesion(
    storage,
    usuario_id: str,
    session_epoch: int,
    ultima_actividad_utc: datetime,
    minutos_inactividad: int | None = None,
) -> bool:
    """Revalida en cada rerun: el usuario sigue activo, el session_epoch
    coincide (no hubo cambio de clave/reset en otra sesión), y la sesión
    no venció por inactividad."""
    df = storage.read_sheet(schema.USUARIOS)
    fila_df = df[df["id"] == usuario_id]
    if fila_df.empty:
        return False
    fila = fila_df.iloc[0]
    if not bool(fila["activo"]):
        return False
    if int(fila["session_epoch"]) != session_epoch:
        return False
    minutos = minutos_inactividad if minutos_inactividad is not None else SESION_MINUTOS_DEFAULT
    inactividad = now_utc() - ultima_actividad_utc
    return inactividad.total_seconds() <= minutos * 60
