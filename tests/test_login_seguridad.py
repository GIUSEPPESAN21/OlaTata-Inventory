"""Login: pausa creciente ante fallos seguidos (freno a la fuerza bruta),
registro del ingreso en auditoría y fecha de inicio de la sesión."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _script(db_path: str) -> None:  # corre DENTRO de AppTest
    import streamlit as st

    from core import auth
    from core.storage import Storage
    from views import ViewContext, login

    if "_storage" not in st.session_state:
        storage = Storage(local_path=db_path, sync_enabled=False)
        with storage.transaction() as tx:
            auth.crear_usuario(tx, nombre="Dueña", usuario="duena", password_plano="Cartera7Rosa",
                               rol="admin", must_change_password=False, permitir_sin_sesion=True)
        st.session_state["_storage"] = storage
    login.render(ViewContext(storage=st.session_state["_storage"], usuario=None, rerun=st.rerun))


def _intentar(at: AppTest, usuario: str, clave: str) -> None:
    at.text_input[0].input(usuario)
    at.text_input[1].input(clave)
    at.button[0].click().run()
    assert not at.exception


def test_pausa_creciente_y_registro_del_ingreso(tmp_path, monkeypatch):
    pausas: list[float] = []
    monkeypatch.setattr("views.login._esperar", lambda s: pausas.append(s))
    at = AppTest.from_function(_script, args=(str(tmp_path / "db.xlsx"),), default_timeout=30)
    at.run()
    for i in range(5):
        _intentar(at, "intruso", f"clave-{i}")
        assert at.error[0].value == "Usuario o contraseña incorrectos."  # mensaje genérico
    assert pausas == [1.0, 2.0, 4.0]  # intentos 3, 4 y 5

    _intentar(at, "duena", "Cartera7Rosa")
    sesion = at.session_state["sesion"]
    assert sesion["usuario"] == "duena" and sesion["inicio_utc"] == sesion["ultima_actividad_utc"]
    assert "_ot_login_fallos" not in at.session_state  # el contador se reinicia al entrar
    from core import schema

    auditoria = at.session_state["_storage"].read_sheet(schema.AUDITORIA)
    assert list(auditoria["accion"]) == ["ingreso"]
