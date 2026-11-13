"""Rol maestro: edición de usuarios y ventas, protección de la cuenta
maestra y datos de prueba (crear y eliminar sin dejar rastros)."""
from __future__ import annotations

import pytest

from core import auth, datos_prueba, edicion_ventas, inventory, schema, seguridad
from core.permissions import CAPABILITIES, PermisoDenegadoError, nombre_rol


def _base(storage):
    with storage.transaction() as tx:
        auth.crear_usuario(tx, nombre="Joseph", usuario="giuseppesan", password_plano="Cartera7Rosa",
                           rol="admin", must_change_password=False, permitir_sin_sesion=True)
        auth.crear_usuario(tx, nombre="Isabella", usuario="ISA", password_plano="Cartera7Rosa",
                           rol="vendedor", must_change_password=False, rol_llamador="admin")
        auth.crear_usuario(tx, nombre="Socia", usuario="socia", password_plano="Cartera7Rosa",
                           rol="admin", must_change_password=False, rol_llamador="admin")
        seguridad.asegurar_maestro(tx)
    return storage


def _usuarios(storage):
    return storage.read_sheet(schema.USUARIOS).set_index("usuario")


def test_maestro_tiene_todo_lo_de_admin_y_vendedor():
    assert CAPABILITIES["admin"] < CAPABILITIES["maestro"]
    assert CAPABILITIES["vendedor"] < CAPABILITIES["maestro"]
    assert {"editar_usuarios", "editar_venta", "datos_prueba"} <= CAPABILITIES["maestro"] - CAPABILITIES["admin"]
    assert nombre_rol("maestro") == "Maestro" and nombre_rol("otro") == "Otro"


def test_el_primer_administrador_queda_como_maestro_una_sola_vez(storage):
    _base(storage)
    u = _usuarios(storage)
    assert u.loc["giuseppesan", "rol"] == "maestro"
    assert u.loc["socia", "rol"] == "admin"
    with storage.transaction() as tx:
        assert seguridad.asegurar_maestro(tx) is None
    assert seguridad.eventos_recientes(storage, "maestro")["accion"].tolist().count("asignar_maestro") == 1


def test_sin_administradores_no_promueve_a_nadie(storage):
    with storage.transaction() as tx:
        assert seguridad.asegurar_maestro(tx) is None


def test_admin_no_puede_tocar_la_cuenta_maestra(storage):
    _base(storage)
    u = _usuarios(storage)
    maestro, socia = u.loc["giuseppesan", "id"], u.loc["socia", "id"]
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            seguridad.restablecer_password(tx, "admin", socia, maestro)
    with pytest.raises(ValueError, match="maestra"):
        with storage.transaction() as tx:
            seguridad.cambiar_estado_usuario(tx, "admin", socia, maestro, activo=False)
    with pytest.raises(PermisoDenegadoError):
        with storage.transaction() as tx:
            seguridad.editar_usuario(tx, "admin", socia, maestro, nombre="Hackeado")


def test_maestro_edita_nombre_usuario_y_rol_y_revoca_sesiones(storage):
    _base(storage)
    u = _usuarios(storage)
    maestro, isa = u.loc["giuseppesan", "id"], u.loc["ISA", "id"]
    epoch = int(u.loc["ISA", "session_epoch"])
    with storage.transaction() as tx:
        cambios = seguridad.editar_usuario(tx, "maestro", maestro, isa, nombre="Isabella Azcárate",
                                           usuario="isa", rol="admin")
    assert cambios == ["nombre", "usuario", "rol"]
    fila = _usuarios(storage).loc["isa"]
    assert fila["rol"] == "admin" and int(fila["session_epoch"]) == epoch + 1
    assert auth.login(storage, "isa", "Cartera7Rosa").ok  # la clave no cambia
    with storage.transaction() as tx:  # sin cambios reales
        assert seguridad.editar_usuario(tx, "maestro", maestro, isa, nombre="Isabella Azcárate") == []


@pytest.mark.parametrize(
    "kwargs,mensaje",
    [
        ({"usuario": "socia"}, "ya existe"),
        ({"usuario": "Con Espacio"}, "minúsculas"),
        ({"rol": "maestro"}, "Administrador o Vendedor"),
        ({"nombre": "   "}, "vacío"),
    ],
)
def test_editar_usuario_valida(storage, kwargs, mensaje):
    _base(storage)
    u = _usuarios(storage)
    with pytest.raises(ValueError, match=mensaje):
        with storage.transaction() as tx:
            seguridad.editar_usuario(tx, "maestro", u.loc["giuseppesan", "id"], u.loc["ISA", "id"], **kwargs)


def test_rol_del_maestro_no_cambia_y_siempre_queda_un_admin(storage):
    _base(storage)
    u = _usuarios(storage)
    maestro, socia = u.loc["giuseppesan", "id"], u.loc["socia", "id"]
    with pytest.raises(ValueError, match="maestro"):
        with storage.transaction() as tx:
            seguridad.editar_usuario(tx, "maestro", maestro, maestro, rol="vendedor")
    with storage.transaction() as tx:  # socia puede pasar a vendedora: el maestro sigue siendo admin
        seguridad.editar_usuario(tx, "maestro", maestro, socia, rol="vendedor")
    with storage.transaction() as tx:  # el maestro sí puede editar su propio nombre
        assert seguridad.editar_usuario(tx, "maestro", maestro, maestro, nombre="Joseph S.") == ["nombre"]


def test_datos_de_prueba_crear_editar_venta_y_eliminar_sin_rastro(storage):
    _base(storage)
    maestro = _usuarios(storage).loc["giuseppesan", "id"]
    antes = {h: len(storage.read_sheet(h)) for h in schema.SHEET_NAMES if h not in (schema.AUDITORIA, schema.CONFIG)}
    with pytest.raises(PermisoDenegadoError):
        datos_prueba.crear_datos_prueba(storage, "admin", "x")

    r = datos_prueba.crear_datos_prueba(storage, "maestro", maestro)
    assert set(r["usuarios"]) == {"prueba.admin", "prueba.vendedor"}
    for usuario, clave in r["usuarios"].items():
        assert auth.login(storage, usuario, clave).ok
    assert datos_prueba.hay_datos_prueba(storage)
    stock = storage.read_sheet(schema.STOCK).set_index("producto_id")
    assert int(stock.loc[r["producto_id"], "cantidad"]) == 8  # 10 - 2 vendidas
    assert inventory.verificar_integridad(storage, "maestro") == []
    with pytest.raises(ValueError, match="Ya existen"):
        datos_prueba.crear_datos_prueba(storage, "maestro", maestro)

    venta = storage.read_sheet(schema.VENTAS).iloc[0]
    assert venta["vendedor_nombre"] == "Vendedor de prueba" and int(venta["total"]) == 196000
    cambios = edicion_ventas.editar_venta(storage, "maestro", maestro, venta["id"],
                                          {"cliente_nombre": "María", "canal": "instagram", "nota": "=1+1"})
    assert cambios == ["cliente_nombre", "canal", "nota"]
    editada = storage.read_sheet(schema.VENTAS).iloc[0]
    assert editada["canal"] == "instagram" and editada["nota"] == "=1+1"  # texto literal, nunca fórmula
    assert int(editada["total"]) == 196000  # el dinero no se toca

    quitadas = datos_prueba.eliminar_datos_prueba(storage, "maestro", maestro)
    assert quitadas[schema.USUARIOS] == 2 and quitadas[schema.VENTAS] == 1
    despues = {h: len(storage.read_sheet(h)) for h in antes}
    assert despues == antes
    assert not datos_prueba.hay_datos_prueba(storage)
    acciones = set(seguridad.eventos_recientes(storage, "maestro")["accion"])
    assert {"crear_datos_prueba", "editar_venta", "eliminar_datos_prueba"} <= acciones


def test_editar_venta_reglas(storage):
    _base(storage)
    maestro = _usuarios(storage).loc["giuseppesan", "id"]
    r = datos_prueba.crear_datos_prueba(storage, "maestro", maestro)
    venta_id = storage.read_sheet(schema.VENTAS).iloc[0]["id"]
    with pytest.raises(PermisoDenegadoError):
        edicion_ventas.editar_venta(storage, "admin", "x", venta_id, {"nota": "x"})
    with pytest.raises(ValueError, match="no se pueden editar"):
        edicion_ventas.editar_venta(storage, "maestro", maestro, venta_id, {"total": 1})
    with pytest.raises(ValueError, match="Canal"):
        edicion_ventas.editar_venta(storage, "maestro", maestro, venta_id, {"canal": "tiktok"})
    with pytest.raises(ValueError, match="no existe"):
        edicion_ventas.editar_venta(storage, "maestro", maestro, "V-nope", {"nota": "x"})
    assert edicion_ventas.editar_venta(storage, "maestro", maestro, venta_id, {"canal": "tienda"}) == []
    from core.returns import anular_venta

    anular_venta(storage, "maestro", r["venta_numero"], "prueba de anulación", usuario_id=maestro)
    with pytest.raises(ValueError, match="anulada"):
        edicion_ventas.editar_venta(storage, "maestro", maestro, venta_id, {"nota": "x"})


def test_eliminar_no_borra_ventas_reales_mezcladas(storage):
    _base(storage)
    u = _usuarios(storage)
    maestro = u.loc["giuseppesan", "id"]
    r = datos_prueba.crear_datos_prueba(storage, "maestro", maestro)
    real = inventory.crear_producto(storage, "maestro", nombre="Bolso real", usuario_id=maestro,
                                    costo=1000, precio=2000, stock_inicial=5)
    from core.sales import confirmar_venta

    confirmar_venta(
        storage, "maestro", "mezcla-1",
        items=[{"producto_id": r["producto_id"], "cantidad": 1, "precio_unitario": 98000, "costo_unitario": 45000,
                "nombre_snapshot": "[PRUEBA] Bolso de prueba"},
               {"producto_id": real["id"], "cantidad": 1, "precio_unitario": 2000, "costo_unitario": 1000,
                "nombre_snapshot": "Bolso real"}],
        pagos=[{"metodo": "efectivo", "monto": 100000}], vendedor_id=maestro, vendedor_nombre="Joseph",
    )
    with pytest.raises(ValueError, match="productos reales"):
        datos_prueba.eliminar_datos_prueba(storage, "maestro", maestro)
    assert datos_prueba.hay_datos_prueba(storage)  # no se tocó nada
