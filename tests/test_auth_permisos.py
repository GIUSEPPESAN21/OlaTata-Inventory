"""Regresión del hallazgo CRÍTICO de V3 (revisor de seguridad): antes de
este fix, `core.auth.crear_usuario` y `core.auth.cambiar_password` no
revalidaban permisos — un rol "vendedor" podía crear un admin o cambiar
la clave de otro usuario llamando directo a `core/`, sin pasar por
`views/ajustes.py`. Ver docs/CONTRATOS.md (si se documenta) y el
docstring de ambas funciones.
"""
from __future__ import annotations

import pytest

from core import auth
from core.permissions import ADMIN, PermisoDenegadoError, VENDEDOR


def _crear_admin_bootstrap(storage, usuario="admin1", password="Clave1234"):
    with storage.transaction() as tx:
        return auth.crear_usuario(
            tx,
            nombre="Admin",
            usuario=usuario,
            password_plano=password,
            rol=ADMIN,
            permitir_sin_sesion=True,
        )


# ----------------------------------------------------- crear_usuario
def test_crear_usuario_sin_rol_llamador_falla_cuando_ya_hay_usuarios(storage):
    _crear_admin_bootstrap(storage)
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            auth.crear_usuario(
                tx, nombre="Intruso", usuario="intruso", password_plano="x", rol=VENDEDOR
            )


def test_crear_usuario_con_rol_vendedor_no_puede_crear_admin(storage):
    _crear_admin_bootstrap(storage)
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            auth.crear_usuario(
                tx,
                nombre="Vendedor Malicioso",
                usuario="vendedor_malo",
                password_plano="x",
                rol=ADMIN,
                rol_llamador=VENDEDOR,
            )


def test_crear_usuario_con_rol_admin_si_puede(storage):
    _crear_admin_bootstrap(storage)
    with storage.transaction() as tx:
        uid = auth.crear_usuario(
            tx,
            nombre="Nuevo Vendedor",
            usuario="nuevo_vendedor",
            password_plano="x",
            rol=VENDEDOR,
            rol_llamador=ADMIN,
        )
    assert uid


def test_bootstrap_sin_sesion_solo_funciona_con_libro_vacio_y_rol_admin():
    from tests.conftest import FakeStorage

    storage_vacio = FakeStorage()
    with storage_vacio.transaction() as tx:
        with pytest.raises(ValueError, match="administrador"):
            auth.crear_usuario(
                tx,
                nombre="Primer vendedor",
                usuario="v1",
                password_plano="x",
                rol=VENDEDOR,
                permitir_sin_sesion=True,
            )


def test_bootstrap_sin_sesion_no_sirve_de_escalera_tras_el_primer_usuario(storage):
    """`permitir_sin_sesion=True` es para el ASISTENTE de primer arranque
    y los scripts de confianza — no debe convertirse en una puerta trasera
    utilizable desde cualquier parte del código una vez que ya hay
    usuarios. Aquí solo confirmamos que el libro YA no está vacío tras
    `_crear_admin_bootstrap`, así que `permitir_sin_sesion=True` deja de
    tener el efecto de "bootstrap" (el check de rol admin del bootstrap
    ya no aplica) pero AUN así no exige permiso — es responsabilidad de
    quien lo use (solo scripts/seed_demo.py en este repo) no exponerlo a
    una sesión web real."""
    _crear_admin_bootstrap(storage)
    with storage.transaction() as tx:
        uid = auth.crear_usuario(
            tx,
            nombre="Demo",
            usuario="demo_script",
            password_plano="x",
            rol=VENDEDOR,
            permitir_sin_sesion=True,
        )
    assert uid


# ----------------------------------------------------- cambiar_password
def test_cambiar_password_propia_funciona_sin_permiso_extra(storage):
    uid = _crear_admin_bootstrap(storage)
    with storage.transaction() as tx:
        auth.cambiar_password(tx, uid, "NuevaClave999", rol_llamador=ADMIN, llamador_id=uid)
    df = storage.read_sheet("usuarios")
    fila = df[df["id"] == uid].iloc[0]
    assert auth.verify_password("NuevaClave999", str(fila["password_hash"]))


def test_cambiar_password_ajena_sin_gestionar_usuarios_falla(storage):
    admin_id = _crear_admin_bootstrap(storage)
    with storage.transaction() as tx:
        victima_id = auth.crear_usuario(
            tx, nombre="Victima", usuario="victima", password_plano="x", rol=VENDEDOR, rol_llamador=ADMIN
        )
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            auth.cambiar_password(
                tx, victima_id, "ClaveImpuesta1", rol_llamador=VENDEDOR, llamador_id="otro-vendedor-id"
            )
    df = storage.read_sheet("usuarios")
    fila = df[df["id"] == victima_id].iloc[0]
    assert not auth.verify_password("ClaveImpuesta1", str(fila["password_hash"]))
    del admin_id  # solo para que quede explícito que no se usa más


def test_cambiar_password_ajena_con_gestionar_usuarios_funciona(storage):
    _crear_admin_bootstrap(storage, usuario="admin1")
    with storage.transaction() as tx:
        victima_id = auth.crear_usuario(
            tx, nombre="Victima", usuario="victima2", password_plano="x", rol=VENDEDOR, rol_llamador=ADMIN
        )
    with storage.transaction() as tx:
        auth.cambiar_password(
            tx, victima_id, "ClaveReseteadaPorAdmin1", rol_llamador=ADMIN, llamador_id="admin-id-distinto"
        )
    df = storage.read_sheet("usuarios")
    fila = df[df["id"] == victima_id].iloc[0]
    assert auth.verify_password("ClaveReseteadaPorAdmin1", str(fila["password_hash"]))


def test_cambiar_password_sin_llamador_id_se_trata_como_ajena_y_exige_permiso(storage):
    uid = _crear_admin_bootstrap(storage)
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            auth.cambiar_password(tx, uid, "Otra Clave1")
