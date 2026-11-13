"""Controles de seguridad de cuentas (core/seguridad.py)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from core import auth, schema, seguridad
from core.permissions import PermisoDenegadoError
from core.timeutil import now_utc, to_iso_utc


@pytest.mark.parametrize(
    "clave,valida",
    [
        ("Cartera7Rosa", True),
        ("Abc12345", False),  # corta
        ("soloLetrasLargas", False),  # sin números
        ("12345678901", False),  # sin letras
        ("aaaa1111aaaa", False),  # casi sin variedad
        ("password2026", False),  # común
        ("OlaTata2026x", False),  # contiene el nombre del negocio
    ],
)
def test_politica_de_contrasenas(clave, valida):
    assert (seguridad.evaluar_password(clave) is None) is valida


def test_contrasena_no_puede_contener_usuario_ni_nombre():
    assert seguridad.evaluar_password("Vende2026xyz", usuario="vende") is not None
    assert seguridad.evaluar_password("Carolina99zz", nombre="Carolina Ruiz") is not None
    assert seguridad.evaluar_password("Cartera7Rosa", usuario="vende", nombre="Carolina Ruiz") is None


def test_clave_temporal_siempre_cumple_la_politica():
    for _ in range(200):
        clave = seguridad.generar_password_temporal()
        assert seguridad.evaluar_password(clave) is None
        assert not set(clave) & set("0OIlo1")  # sin caracteres confusos


@pytest.mark.parametrize("usuario,ok", [("vende", True), ("maria.p_2", True), ("Ma", False), ("con espacio", False),
                                        ("josé", False), ("ADMIN", False), ("а" * 4, False)])
def test_nombre_de_usuario(usuario, ok):
    assert (seguridad.validar_nombre_usuario(usuario) is None) is ok


def _crear(storage, usuario, rol, admin_rol="admin"):
    with storage.transaction() as tx:
        return auth.crear_usuario(
            tx, nombre=usuario.title(), usuario=usuario, password_plano="Cartera7Rosa", rol=rol,
            must_change_password=False, rol_llamador=admin_rol,
        )


def test_restablecer_clave_revoca_sesiones_y_obliga_cambio(storage):
    admin = _crear(storage, "duena", "admin")
    vende = _crear(storage, "vende", "vendedor")
    epoch_antes = int(storage.read_sheet(schema.USUARIOS).set_index("id").loc[vende, "session_epoch"])
    with storage.transaction() as tx:
        clave = seguridad.restablecer_password(tx, "admin", admin, vende)
    fila = storage.read_sheet(schema.USUARIOS).set_index("id").loc[vende]
    assert bool(fila["must_change_password"]) is True
    assert int(fila["session_epoch"]) == epoch_antes + 1  # sesiones abiertas quedan inválidas
    assert auth.login(storage, "vende", clave).ok
    assert not auth.login(storage, "vende", "Cartera7Rosa").ok
    eventos = seguridad.eventos_recientes(storage, "admin")
    assert eventos.iloc[0]["accion"] == "restablecer_clave"
    assert "Cartera7Rosa" not in eventos.to_string() and clave not in eventos.to_string()


def test_restablecer_exige_permiso_y_no_aplica_a_uno_mismo(storage):
    admin = _crear(storage, "duena", "admin")
    vende = _crear(storage, "vende", "vendedor")
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            seguridad.restablecer_password(tx, "vendedor", vende, admin)
    with pytest.raises(ValueError):
        with storage.transaction() as tx:
            seguridad.restablecer_password(tx, "admin", admin, admin)


def test_nunca_queda_el_negocio_sin_administrador(storage):
    admin = _crear(storage, "duena", "admin")
    vende = _crear(storage, "vende", "vendedor")
    with pytest.raises(ValueError, match="propia"):
        with storage.transaction() as tx:
            seguridad.cambiar_estado_usuario(tx, "admin", admin, admin, activo=False)
    admin2 = _crear(storage, "socia", "admin")
    with storage.transaction() as tx:  # con otro admin activo sí se puede
        seguridad.cambiar_estado_usuario(tx, "admin", admin2, admin, activo=False)
    with pytest.raises(ValueError, match="al menos un administrador"):
        with storage.transaction() as tx:  # simulación: alguien intenta dejar 0 admins
            seguridad.cambiar_estado_usuario(tx, "admin", "U-otro", admin2, activo=False)
    with storage.transaction() as tx:
        seguridad.cambiar_estado_usuario(tx, "admin", admin2, vende, activo=False)
    assert not auth.login(storage, "vende", "Cartera7Rosa").ok
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            seguridad.cambiar_estado_usuario(tx, "vendedor", vende, admin2, activo=False)


def test_registro_de_auditoria_y_permiso_para_verlo(storage):
    with storage.transaction() as tx:
        seguridad.registrar_evento(tx, "U-000001", "ingreso", "=HYPERLINK(\"http://x\")")
        seguridad.registrar_evento(tx, None, "prueba")
    eventos = seguridad.eventos_recientes(storage, "admin")
    assert len(eventos) == 2 and set(eventos["usuario"]) == {"U-000001", "sistema"}
    # Regla 5: el texto con "=" se conserva literal (se escribe como texto, nunca fórmula: ver test_fastxlsx)
    assert eventos[eventos["accion"] == "ingreso"].iloc[0]["detalle"] == '=HYPERLINK("http://x")'
    with pytest.raises(PermisoDenegadoError):
        seguridad.eventos_recientes(storage, "vendedor")
    assert seguridad.eventos_recientes(storage, "admin", limite=1).shape[0] == 1


def test_auditoria_vacia(storage):
    assert seguridad.eventos_recientes(storage, "admin").empty


def test_pausa_creciente_tras_fallos():
    assert [seguridad.pausa_tras_fallos(n) for n in range(8)] == [0, 0, 1, 2, 4, 8, 8, 8]


def test_duracion_maxima_de_sesion():
    ahora = now_utc()
    assert not seguridad.sesion_excede_maximo(None)
    assert not seguridad.sesion_excede_maximo(to_iso_utc(ahora - timedelta(hours=11)), ahora=ahora)
    assert seguridad.sesion_excede_maximo(to_iso_utc(ahora - timedelta(hours=13)), ahora=ahora)
    assert seguridad.sesion_excede_maximo("no-es-fecha")


def test_guias_cubren_cada_pantalla_y_pestana():
    import re
    from pathlib import Path

    from core.guias import GUIAS, obtener_guia

    raiz = Path(__file__).resolve().parent.parent
    usadas = set()
    for vista in (raiz / "views").glob("*.py"):
        usadas |= set(re.findall(r'guia\("([a-z_]+)"\)', vista.read_text(encoding="utf-8")))
    assert usadas == set(GUIAS), f"guías sin usar o inexistentes: {usadas ^ set(GUIAS)}"
    for g in GUIAS.values():
        assert g.titulo and len(g.pasos) >= 2
    with pytest.raises(KeyError):
        obtener_guia("no-existe")


def test_md_seguro_neutraliza_markdown_y_latex():
    from core.ui import md_seguro

    texto = md_seguro("[Paga aquí](http://x) **$ 1.000**")
    assert "](" not in texto.replace("\\](", "").replace("\\(", "")
    assert "\\$" in texto and "\\*" in texto
    assert isinstance(pd.Series([md_seguro(5)])[0], str)
