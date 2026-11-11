from datetime import timedelta

from core import auth
from core.timeutil import now_utc


def _crear_admin(storage, usuario="joseph", password="Clave1234"):
    with storage.transaction() as tx:
        uid = auth.crear_usuario(
            tx, nombre="Joseph", usuario=usuario, password_plano=password, rol="admin", must_change_password=True
        )
    return uid


def test_hash_y_verify_password_roundtrip():
    h = auth.hash_password("Secreta123")
    assert auth.verify_password("Secreta123", h)
    assert not auth.verify_password("otra-clave", h)


def test_login_exitoso(storage):
    _crear_admin(storage)
    resultado = auth.login(storage, "joseph", "Clave1234")
    assert resultado.ok
    assert resultado.usuario.usuario == "joseph"
    assert resultado.usuario.rol == "admin"


def test_login_password_incorrecta_mensaje_generico(storage):
    _crear_admin(storage)
    resultado = auth.login(storage, "joseph", "clave-mala")
    assert not resultado.ok
    assert resultado.motivo == "Usuario o contraseña incorrectos."


def test_login_usuario_inexistente_mismo_mensaje_generico(storage):
    resultado = auth.login(storage, "no-existe", "cualquiera")
    assert not resultado.ok
    assert resultado.motivo == "Usuario o contraseña incorrectos."


def test_login_usuario_inactivo_rechazado(storage):
    uid = _crear_admin(storage)
    with storage.transaction() as tx:
        df = tx.read_sheet("usuarios")
        df.loc[df["id"] == uid, "activo"] = False
        tx.write_sheet("usuarios", df)
    resultado = auth.login(storage, "joseph", "Clave1234")
    assert not resultado.ok


def test_bloqueo_tras_demasiados_intentos_fallidos(storage):
    _crear_admin(storage)
    for _ in range(auth.MAX_INTENTOS):
        resultado = auth.login(storage, "joseph", "clave-mala")
        assert not resultado.ok
    bloqueado = auth.login(storage, "joseph", "Clave1234")  # incluso con la clave correcta
    assert not bloqueado.ok
    assert "intentos" in bloqueado.motivo.lower()


def test_no_se_puede_crear_usuario_duplicado(storage):
    _crear_admin(storage)
    with storage.transaction() as tx:
        try:
            auth.crear_usuario(tx, nombre="Otro", usuario="joseph", password_plano="x", rol="vendedor")
            assert False, "debía lanzar ValueError"
        except ValueError:
            pass


def test_cambiar_password_incrementa_session_epoch_y_quita_flag(storage):
    uid = _crear_admin(storage)
    with storage.transaction() as tx:
        auth.cambiar_password(tx, uid, "NuevaClave999")
    df = storage.read_sheet("usuarios")
    fila = df[df["id"] == uid].iloc[0]
    assert int(fila["session_epoch"]) == 2
    assert bool(fila["must_change_password"]) is False
    assert auth.verify_password("NuevaClave999", str(fila["password_hash"]))


def test_validar_sesion_rechaza_epoch_desactualizado(storage):
    uid = _crear_admin(storage)
    with storage.transaction() as tx:
        auth.cambiar_password(tx, uid, "NuevaClave999")
    # sesión vieja con epoch=1 ya no es válida tras el cambio de clave (epoch=2)
    assert not auth.validar_sesion(storage, uid, session_epoch=1, ultima_actividad_utc=now_utc())


def test_validar_sesion_rechaza_por_inactividad(storage):
    uid = _crear_admin(storage)
    hace_rato = now_utc() - timedelta(minutes=auth.SESION_MINUTOS_DEFAULT + 1)
    assert not auth.validar_sesion(storage, uid, session_epoch=1, ultima_actividad_utc=hace_rato)


def test_validar_sesion_acepta_dentro_del_limite(storage):
    uid = _crear_admin(storage)
    hace_poco = now_utc() - timedelta(minutes=5)
    assert auth.validar_sesion(storage, uid, session_epoch=1, ultima_actividad_utc=hace_poco)
