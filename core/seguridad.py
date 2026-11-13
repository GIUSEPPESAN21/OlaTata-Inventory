"""Controles de seguridad de cuentas y registro de auditoría.

- Política de contraseñas (mínimo 10 caracteres, letras y números, no
  contener el usuario ni ser una clave común).
- Claves temporales que SIEMPRE cumplen la política.
- Restablecer la clave de otro usuario (solo admin): nueva clave temporal,
  cambio obligatorio al ingresar y cierre de TODAS sus sesiones abiertas.
- Activar/desactivar usuarios sin poder dejar el negocio sin
  administrador (ni desactivarse a uno mismo).
- Registro de auditoría en la hoja `auditoria`: ingresos, cambios de
  clave, usuarios creados/activados/desactivados, conflictos resueltos.
- Freno a la fuerza bruta en el login (pausa creciente por sesión del
  navegador) y duración máxima absoluta de una sesión.

Permisos revalidados aquí (CLAUDE.md regla 4). Texto libre por
`excel_safe` (regla 5). Toda escritura dentro de `storage.transaction()`.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta

import pandas as pd

from core import auth, schema
from core.excel_safe import excel_safe
from core.permissions import ADMIN, MAESTRO, ROLES_ADMINISTRATIVOS, VENDEDOR, PermisoDenegadoError, requerir
from core.timeutil import now_utc, parse_iso_utc, to_iso_utc

__all__ = [
    "PASSWORD_MIN",
    "SESION_MAX_HORAS",
    "evaluar_password",
    "validar_nombre_usuario",
    "generar_password_temporal",
    "registrar_evento",
    "eventos_recientes",
    "restablecer_password",
    "cambiar_estado_usuario",
    "editar_usuario",
    "asegurar_maestro",
    "pausa_tras_fallos",
    "sesion_excede_maximo",
]

PASSWORD_MIN = 10
SESION_MAX_HORAS = 12

# Claves que aparecen primero en cualquier diccionario de ataque (en
# minúscula, sin espacios). Se compara también "contiene".
_CLAVES_COMUNES = frozenset(
    {
        "1234567890", "12345678910", "0123456789", "contraseña", "contrasena", "password",
        "password1", "qwertyuiop", "asdfghjkl", "olatata", "ola tata", "olatata123",
        "bolsos", "accesorios", "colombia", "buga", "tulua", "administrador", "admin",
        "vendedor", "iloveyou", "abc123", "123456", "111111", "000000", "qwerty",
    }
)


def evaluar_password(password: str | None, *, usuario: str | None = None, nombre: str | None = None) -> str | None:
    """`None` si la clave cumple la política; si no, el motivo en español
    listo para mostrar. Se aplica al crear, cambiar o restablecer claves."""
    clave = password or ""
    if len(clave) < PASSWORD_MIN:
        return f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres."
    if not any(c.isalpha() for c in clave) or not any(c.isdigit() for c in clave):
        return "La contraseña debe combinar letras y números."
    if len(set(clave)) < 4:
        return "La contraseña repite demasiado los mismos caracteres."
    baja = clave.lower().replace(" ", "")
    if baja in _CLAVES_COMUNES or any(c in baja for c in _CLAVES_COMUNES if len(c) >= 6):
        return "Esa contraseña es demasiado común. Elige otra."
    for dato in (usuario, *(nombre or "").split()):
        dato = (dato or "").strip().lower()
        if len(dato) >= 3 and dato in baja:
            return "La contraseña no puede contener tu usuario ni tu nombre."
    return None


def validar_nombre_usuario(usuario: str | None) -> str | None:
    """Usuarios de 3 a 30 caracteres: minúsculas, números, punto, guion o
    guion bajo. Evita espacios invisibles, mayúsculas que confunden y
    caracteres que parecen otros (p.ej. letras cirílicas)."""
    import re

    valor = (usuario or "").strip()
    if not re.fullmatch(r"[a-z0-9._-]{3,30}", valor):
        return "El usuario debe tener de 3 a 30 caracteres: minúsculas, números, punto, guion o guion bajo (sin espacios ni tildes)."
    return None


def generar_password_temporal(longitud: int = 12) -> str:
    """Aleatoria (módulo `secrets`), sin caracteres confusos (0/O, 1/l/I),
    y que siempre cumple `evaluar_password`."""
    longitud = max(longitud, PASSWORD_MIN)
    letras = "".join(c for c in string.ascii_letters if c not in "OIlo")
    digitos = "23456789"
    alfabeto = letras + digitos
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(longitud))
        if evaluar_password(clave) is None:
            return clave


# ------------------------------------------------------------ auditoría
def registrar_evento(tx, usuario: str | None, accion: str, detalle: str = "") -> None:
    """Agrega una fila a `auditoria` (dentro de `transaction()`). Nunca
    guarda contraseñas: solo quién, qué y cuándo."""
    ahora = to_iso_utc(now_utc())
    numero = tx.next_counter("auditoria")
    fila = {
        "id": f"AUD-{numero:07d}",
        "ts": ahora,
        "usuario": excel_safe(str(usuario or "sistema"), max_length=120, field_name="usuario"),
        "accion": excel_safe(accion, max_length=60, field_name="accion"),
        "detalle": excel_safe(detalle or "", max_length=500, field_name="detalle"),
        "created_at": ahora,
        "updated_at": ahora,
    }
    df = tx.read_sheet(schema.AUDITORIA)
    tx.write_sheet(schema.AUDITORIA, pd.concat([df, pd.DataFrame([fila])], ignore_index=True))


def eventos_recientes(storage, rol: str | None, limite: int = 50) -> pd.DataFrame:
    """Últimos eventos de auditoría (solo admin)."""
    requerir(rol, "gestionar_usuarios")
    df = storage.read_sheet(schema.AUDITORIA)
    if df.empty:
        return df
    return df.sort_values("ts", ascending=False).head(limite).reset_index(drop=True)


# ---------------------------------------------------- gestión de cuentas
def _fila_usuario(df: pd.DataFrame, usuario_id: str) -> pd.Series:
    coincide = df["id"] == usuario_id
    if not coincide.any():
        raise ValueError(f"Usuario '{usuario_id}' no existe.")
    return df[coincide].iloc[0]


def restablecer_password(tx, rol_llamador: str | None, llamador_id: str | None, usuario_id: str) -> str:
    """Admin restablece la clave de OTRO usuario. Devuelve la clave temporal
    (se muestra una sola vez). Obliga a cambiarla al ingresar y revoca
    todas las sesiones abiertas de ese usuario (sube `session_epoch`)."""
    requerir(rol_llamador, "gestionar_usuarios")
    if usuario_id == llamador_id:
        raise ValueError("Para cambiar tu propia clave usa la opción de cambio de contraseña.")
    df = tx.read_sheet(schema.USUARIOS)
    fila = _fila_usuario(df, usuario_id)
    _proteger_maestro(fila, rol_llamador, "restablecer la clave del maestro")
    clave = generar_password_temporal()
    coincide = df["id"] == usuario_id
    df.loc[coincide, "password_hash"] = auth.hash_password(clave)
    df.loc[coincide, "must_change_password"] = True
    df.loc[coincide, "session_epoch"] = df.loc[coincide, "session_epoch"].astype(int) + 1
    df.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
    tx.write_sheet(schema.USUARIOS, df)
    registrar_evento(tx, llamador_id, "restablecer_clave", f"usuario={fila['usuario']}")
    return clave


def _proteger_maestro(fila: pd.Series, rol_llamador: str | None, accion: str) -> None:
    if fila["rol"] == MAESTRO and rol_llamador != MAESTRO:
        raise PermisoDenegadoError(str(rol_llamador), accion)


def cambiar_estado_usuario(
    tx, rol_llamador: str | None, llamador_id: str | None, usuario_id: str, *, activo: bool
) -> None:
    """Activa o desactiva una cuenta. Al desactivar, sus sesiones se cierran
    en el siguiente clic. Nunca deja al negocio sin un administrador
    activo, ni permite desactivarse a uno mismo."""
    requerir(rol_llamador, "gestionar_usuarios")
    df = tx.read_sheet(schema.USUARIOS)
    fila = _fila_usuario(df, usuario_id)
    if not activo:
        if usuario_id == llamador_id:
            raise ValueError("No puedes desactivar tu propia cuenta.")
        if fila["rol"] == MAESTRO:
            raise ValueError("La cuenta maestra no se puede desactivar.")
        es_admin = df["rol"].isin(ROLES_ADMINISTRATIVOS)
        admins_activos = df[es_admin & (df["activo"].astype(bool)) & (df["id"] != usuario_id)]
        if fila["rol"] in ROLES_ADMINISTRATIVOS and admins_activos.empty:
            raise ValueError("Debe quedar al menos un administrador activo.")
    coincide = df["id"] == usuario_id
    df.loc[coincide, "activo"] = activo
    df.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
    tx.write_sheet(schema.USUARIOS, df)
    registrar_evento(tx, llamador_id, "activar_usuario" if activo else "desactivar_usuario", f"usuario={fila['usuario']}")


def editar_usuario(
    tx,
    rol_llamador: str | None,
    llamador_id: str | None,
    usuario_id: str,
    *,
    nombre: str | None = None,
    usuario: str | None = None,
    rol: str | None = None,
) -> list[str]:
    """Solo el MAESTRO: cambia nombre, usuario y/o rol (administrador o
    vendedor) de otra cuenta. Si cambia el usuario o el rol, se cierran sus
    sesiones abiertas para que vuelva a entrar con los permisos nuevos.
    Devuelve la lista de campos cambiados."""
    requerir(rol_llamador, "editar_usuarios")
    df = tx.read_sheet(schema.USUARIOS)
    fila = _fila_usuario(df, usuario_id)
    coincide = df["id"] == usuario_id
    cambios: list[str] = []

    if nombre is not None and nombre.strip() != str(fila["nombre"]):
        nombre_seguro = excel_safe(nombre.strip(), max_length=120, field_name="nombre")
        if not nombre_seguro:
            raise ValueError("El nombre no puede quedar vacío.")
        df.loc[coincide, "nombre"] = nombre_seguro
        cambios.append("nombre")
    if usuario is not None and usuario.strip() != str(fila["usuario"]):
        error = validar_nombre_usuario(usuario)
        if error:
            raise ValueError(error)
        if (df.loc[~coincide, "usuario"].astype(str).str.lower() == usuario.strip()).any():
            raise ValueError(f"El usuario '{usuario.strip()}' ya existe.")
        df.loc[coincide, "usuario"] = usuario.strip()
        cambios.append("usuario")
    if rol is not None and rol != fila["rol"]:
        if fila["rol"] == MAESTRO:
            raise ValueError("El rol del maestro no se cambia (siempre debe existir uno).")
        if rol not in (ADMIN, VENDEDOR):
            raise ValueError("El rol debe ser Administrador o Vendedor.")
        if fila["rol"] in ROLES_ADMINISTRATIVOS and rol == VENDEDOR:
            otros = df[df["rol"].isin(ROLES_ADMINISTRATIVOS) & df["activo"].astype(bool) & ~coincide]
            if otros.empty:
                raise ValueError("Debe quedar al menos un administrador activo.")
        df.loc[coincide, "rol"] = rol
        cambios.append("rol")
    if not cambios:
        return []
    if "usuario" in cambios or "rol" in cambios:
        df.loc[coincide, "session_epoch"] = df.loc[coincide, "session_epoch"].astype(int) + 1
    df.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
    tx.write_sheet(schema.USUARIOS, df)
    registrar_evento(tx, llamador_id, "editar_usuario", f"usuario={fila['usuario']} cambios={','.join(cambios)}")
    return cambios


def asegurar_maestro(tx) -> str | None:
    """Si no hay ningún maestro activo, promueve al PRIMER administrador
    creado (el dueño, quien hizo el primer arranque). Devuelve el id
    promovido o `None` si no hizo falta. Idempotente."""
    df = tx.read_sheet(schema.USUARIOS)
    if df.empty or ((df["rol"] == MAESTRO) & df["activo"].astype(bool)).any():
        return None
    admins = df[(df["rol"] == ADMIN) & df["activo"].astype(bool)].sort_values("id")
    if admins.empty:
        return None
    usuario_id = str(admins.iloc[0]["id"])
    coincide = df["id"] == usuario_id
    df.loc[coincide, "rol"] = MAESTRO
    df.loc[coincide, "session_epoch"] = df.loc[coincide, "session_epoch"].astype(int) + 1
    df.loc[coincide, "updated_at"] = to_iso_utc(now_utc())
    tx.write_sheet(schema.USUARIOS, df)
    registrar_evento(tx, "sistema", "asignar_maestro", f"usuario={admins.iloc[0]['usuario']}")
    return usuario_id


# ------------------------------------------------------------- sesiones
def pausa_tras_fallos(fallos: int) -> float:
    """Segundos de espera antes de responder un login fallido, según los
    fallos seguidos en ESTA sesión del navegador: 0, 0, 1, 2, 4, 8, 8…
    Complementa el bloqueo de 15 min por usuario de `core.auth`."""
    if fallos < 2:
        return 0.0
    return float(min(8, 2 ** (fallos - 2)))


def sesion_excede_maximo(inicio_utc: str | None, *, ahora: datetime | None = None) -> bool:
    """Aunque haya actividad, una sesión no dura más de `SESION_MAX_HORAS`.
    Sin fecha de inicio (sesiones anteriores a este control) no vence aquí."""
    if not inicio_utc:
        return False
    try:
        inicio = parse_iso_utc(inicio_utc)
    except Exception:
        return True
    return (ahora or now_utc()) - inicio > timedelta(hours=SESION_MAX_HORAS)
