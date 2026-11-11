"""Pruebas de core/inventory.py: CRUD de productos, conteo físico y
verificación de integridad (R3, R4, R11, §10)."""
from __future__ import annotations

import pytest

from core import inventory, schema
from core.permissions import ADMIN, VENDEDOR, PermisoDenegadoError


# --------------------------------------------------------------------- CRUD
def test_crear_producto_genera_id_autogenerado(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso rosa", usuario_id="U-1", costo=1000, precio=2000
    )
    assert resultado["id"] == "OT-000001"

    otro = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso dorado", usuario_id="U-1", costo=1000, precio=2000
    )
    assert otro["id"] == "OT-000002"


def test_crear_producto_con_stock_inicial_genera_movimiento_apertura(storage):
    resultado = inventory.crear_producto(
        storage,
        ADMIN,
        nombre="Billetera",
        usuario_id="U-1",
        costo=1000,
        precio=2000,
        stock_inicial=7,
    )
    producto_id = resultado["id"]
    stock_df = storage.read_sheet(schema.STOCK)
    fila = stock_df[stock_df["producto_id"] == producto_id].iloc[0]
    assert int(fila["cantidad"]) == 7

    movimientos = storage.read_sheet(schema.MOVIMIENTOS)
    fila_mov = movimientos[movimientos["producto_id"] == producto_id].iloc[0]
    assert fila_mov["tipo"] == "apertura"
    assert int(fila_mov["cantidad"]) == 7
    assert int(fila_mov["stock_antes"]) == 0
    assert int(fila_mov["stock_despues"]) == 7


def test_crear_producto_precio_menor_que_costo_es_advertencia_no_bloqueo(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Cartera liquidación", usuario_id="U-1", costo=5000, precio=3000
    )
    assert resultado["id"]  # se creó igual
    assert len(resultado["advertencias"]) == 1
    assert "costo" in resultado["advertencias"][0].mensaje.lower() or "pérdida" in resultado["advertencias"][0].mensaje.lower()


def test_crear_producto_codigo_barras_duplicado_falla(storage):
    inventory.crear_producto(
        storage, ADMIN, nombre="Bolso A", usuario_id="U-1", costo=1000, precio=2000, codigo_barras="ABC123"
    )
    with pytest.raises(ValueError):
        inventory.crear_producto(
            storage, ADMIN, nombre="Bolso B", usuario_id="U-1", costo=1000, precio=2000, codigo_barras="ABC123"
        )


def test_crear_producto_stock_inicial_negativo_falla(storage):
    with pytest.raises(ValueError):
        inventory.crear_producto(
            storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=-1
        )


def test_crear_producto_nombre_formula_sobrevive_intacto(storage):
    # R11: un texto "=1+1" nunca se trata como fórmula ni se pierde.
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="=1+1", usuario_id="U-1", costo=1000, precio=2000
    )
    productos = storage.read_sheet(schema.PRODUCTOS)
    fila = productos[productos["id"] == resultado["id"]].iloc[0]
    assert fila["nombre"] == "=1+1"


def test_editar_producto_actualiza_solo_campos_pasados(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", categoria="Bolsos", costo=1000, precio=2000
    )
    producto_id = resultado["id"]

    inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", precio=2500)

    productos = storage.read_sheet(schema.PRODUCTOS)
    fila = productos[productos["id"] == producto_id].iloc[0]
    assert int(fila["precio"]) == 2500
    assert fila["categoria"] == "Bolsos"  # no tocado
    assert fila["nombre"] == "Bolso"  # no tocado


def test_editar_producto_codigo_barras_duplicado_falla(storage):
    a = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso A", usuario_id="U-1", costo=1000, precio=2000, codigo_barras="COD-1"
    )
    b = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso B", usuario_id="U-1", costo=1000, precio=2000, codigo_barras="COD-2"
    )
    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id=b["id"], usuario_id="U-1", codigo_barras="COD-1")
    # El propio producto puede conservar su código (no es "duplicado" consigo mismo).
    inventory.editar_producto(storage, ADMIN, producto_id=a["id"], usuario_id="U-1", codigo_barras="COD-1")


def test_editar_producto_inexistente_falla(storage):
    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id="OT-999999", usuario_id="U-1", nombre="x")


def test_desactivar_y_activar_producto_nunca_borra(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000
    )
    producto_id = resultado["id"]

    inventory.desactivar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1")
    productos = storage.read_sheet(schema.PRODUCTOS)
    assert len(productos) == 1  # sigue existiendo la fila
    assert bool(productos.iloc[0]["activo"]) is False

    inventory.activar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1")
    productos = storage.read_sheet(schema.PRODUCTOS)
    assert bool(productos.iloc[0]["activo"]) is True


def test_obtener_producto_existente_y_inexistente(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000
    )
    fila = inventory.obtener_producto(storage, ADMIN, resultado["id"])
    assert fila is not None
    assert fila["nombre"] == "Bolso"

    assert inventory.obtener_producto(storage, ADMIN, "OT-999999") is None


def test_editar_producto_puede_cambiar_costo_y_stock_minimo(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000
    )
    producto_id = resultado["id"]

    inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", costo=1200, stock_minimo=3)

    productos = storage.read_sheet(schema.PRODUCTOS)
    fila = productos[productos["id"] == producto_id].iloc[0]
    assert int(fila["costo"]) == 1200
    assert int(fila["stock_minimo"]) == 3


def test_editar_producto_rechaza_costo_precio_y_stock_minimo_negativos(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000
    )
    producto_id = resultado["id"]

    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", costo=-1)
    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", precio=-1)
    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", stock_minimo=-1)
    with pytest.raises(ValueError):
        inventory.editar_producto(storage, ADMIN, producto_id=producto_id, usuario_id="U-1", nombre="   ")


def test_desactivar_producto_inexistente_falla(storage):
    with pytest.raises(ValueError):
        inventory.desactivar_producto(storage, ADMIN, producto_id="OT-999999", usuario_id="U-1")


# ------------------------------------------------------------- listar/buscar
def test_listar_productos_filtros_categoria_bajo_minimo_sin_stock_busqueda(storage):
    inventory.crear_producto(
        storage,
        ADMIN,
        nombre="Bolso rosa",
        usuario_id="U-1",
        categoria="Bolsos",
        costo=1000,
        precio=2000,
        stock_minimo=5,
        stock_inicial=2,
        codigo_barras="COD-ROSA",
    )
    inventory.crear_producto(
        storage,
        ADMIN,
        nombre="Correa dorada",
        usuario_id="U-1",
        categoria="Accesorios",
        costo=1000,
        precio=2000,
        stock_minimo=1,
        stock_inicial=0,
    )

    todos = inventory.listar_productos(storage, ADMIN)
    assert len(todos) == 2

    solo_bolsos = inventory.listar_productos(storage, ADMIN, categoria="Bolsos")
    assert list(solo_bolsos["nombre"]) == ["Bolso rosa"]

    bajo_minimo = inventory.listar_productos(storage, ADMIN, bajo_minimo=True)
    assert set(bajo_minimo["nombre"]) == {"Bolso rosa", "Correa dorada"}

    sin_stock = inventory.listar_productos(storage, ADMIN, sin_stock=True)
    assert list(sin_stock["nombre"]) == ["Correa dorada"]

    por_codigo = inventory.listar_productos(storage, ADMIN, busqueda="cod-rosa")
    assert list(por_codigo["nombre"]) == ["Bolso rosa"]

    por_nombre = inventory.listar_productos(storage, ADMIN, busqueda="dorada")
    assert list(por_nombre["nombre"]) == ["Correa dorada"]

    solo_activos = inventory.listar_productos(storage, ADMIN, solo_activos=True)
    assert len(solo_activos) == 2


# -------------------------------------------------------------- permisos
def test_vendedor_no_puede_gestionar_inventario(storage):
    with pytest.raises(PermisoDenegadoError):
        inventory.crear_producto(storage, VENDEDOR, nombre="x", usuario_id="U-2", costo=1000, precio=2000)
    with pytest.raises(PermisoDenegadoError):
        inventory.listar_productos(storage, VENDEDOR)


def test_vendedor_no_puede_ajustar_stock_via_conteo(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=5
    )
    with pytest.raises(PermisoDenegadoError):
        inventory.conteo_fisico(
            storage, VENDEDOR, producto_id=resultado["id"], cantidad_contada=3, usuario_id="U-2", motivo="robo"
        )


def test_vendedor_no_puede_verificar_integridad(storage):
    with pytest.raises(PermisoDenegadoError):
        inventory.verificar_integridad(storage, VENDEDOR)


# ---------------------------------------------------------- conteo físico
def test_conteo_fisico_exige_motivo_si_hay_diferencia(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=10
    )
    producto_id = resultado["id"]

    with pytest.raises(ValueError):
        inventory.conteo_fisico(
            storage, ADMIN, producto_id=producto_id, cantidad_contada=8, usuario_id="U-1", motivo=""
        )
    # No se escribió el ajuste: el stock sigue en 10.
    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df[stock_df["producto_id"] == producto_id].iloc[0]["cantidad"]) == 10


def test_conteo_fisico_sin_diferencia_no_requiere_motivo_ni_movimiento(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=10
    )
    producto_id = resultado["id"]
    movimientos_antes = len(storage.read_sheet(schema.MOVIMIENTOS))

    conteo = inventory.conteo_fisico(
        storage, ADMIN, producto_id=producto_id, cantidad_contada=10, usuario_id="U-1"
    )
    assert conteo.diferencia == 0
    assert conteo.movimiento_id is None
    assert len(storage.read_sheet(schema.MOVIMIENTOS)) == movimientos_antes


def test_conteo_fisico_con_motivo_ajusta_stock_y_genera_movimiento(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=10
    )
    producto_id = resultado["id"]

    conteo = inventory.conteo_fisico(
        storage,
        ADMIN,
        producto_id=producto_id,
        cantidad_contada=7,
        usuario_id="U-1",
        motivo="Faltante por merma no reportada",
    )
    assert conteo.diferencia == -3
    assert conteo.movimiento_id is not None

    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df[stock_df["producto_id"] == producto_id].iloc[0]["cantidad"]) == 7

    movimientos = storage.read_sheet(schema.MOVIMIENTOS)
    ajuste = movimientos[movimientos["tipo"] == "ajuste_conteo"].iloc[0]
    assert int(ajuste["cantidad"]) == -3
    assert int(ajuste["stock_antes"]) == 10
    assert int(ajuste["stock_despues"]) == 7


def test_conteo_fisico_no_permite_cantidad_negativa(storage):
    # R3: el stock nunca queda negativo.
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=10
    )
    with pytest.raises(ValueError):
        inventory.conteo_fisico(
            storage, ADMIN, producto_id=resultado["id"], cantidad_contada=-1, usuario_id="U-1", motivo="error"
        )


def test_conteo_fisico_sin_fila_de_stock_previa_crea_una(storage):
    # Un producto creado sin stock_inicial no tiene fila en `stock` todavía.
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=0
    )
    producto_id = resultado["id"]
    assert storage.read_sheet(schema.STOCK).empty

    conteo = inventory.conteo_fisico(
        storage, ADMIN, producto_id=producto_id, cantidad_contada=4, usuario_id="U-1", motivo="Llegó sin registrar"
    )
    assert conteo.stock_sistema == 0
    assert conteo.diferencia == 4

    stock_df = storage.read_sheet(schema.STOCK)
    assert int(stock_df[stock_df["producto_id"] == producto_id].iloc[0]["cantidad"]) == 4


def test_conteo_fisico_producto_inexistente_falla(storage):
    with pytest.raises(ValueError):
        inventory.conteo_fisico(
            storage, ADMIN, producto_id="OT-999999", cantidad_contada=1, usuario_id="U-1", motivo="x"
        )


# --------------------------------------------------------- integridad
def test_verificar_integridad_filtra_por_sede(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=5
    )
    producto_id = resultado["id"]

    # Induce una diferencia en la sede principal.
    with storage.transaction() as tx:
        stock_df = tx.read_sheet(schema.STOCK)
        stock_df.loc[stock_df["producto_id"] == producto_id, "cantidad"] = 999
        tx.write_sheet(schema.STOCK, stock_df)

    diferencias_otra_sede = inventory.verificar_integridad(storage, ADMIN, sede_id="otra_sede_inexistente")
    assert diferencias_otra_sede == []

    diferencias_principal = inventory.verificar_integridad(storage, ADMIN, sede_id=schema.SEDE_PRINCIPAL)
    assert len(diferencias_principal) == 1


def test_verificar_integridad_sin_diferencias(storage):
    inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=5
    )
    diferencias = inventory.verificar_integridad(storage, ADMIN)
    assert diferencias == []


def test_verificar_integridad_detecta_diferencia_inducida(storage):
    resultado = inventory.crear_producto(
        storage, ADMIN, nombre="Bolso", usuario_id="U-1", costo=1000, precio=2000, stock_inicial=5
    )
    producto_id = resultado["id"]

    # Induce una diferencia: cambia la hoja stock directamente, sin pasar por
    # un movimiento (como un dato corrupto o una edición manual indebida).
    with storage.transaction() as tx:
        stock_df = tx.read_sheet(schema.STOCK)
        stock_df.loc[stock_df["producto_id"] == producto_id, "cantidad"] = 999
        tx.write_sheet(schema.STOCK, stock_df)

    diferencias = inventory.verificar_integridad(storage, ADMIN)
    assert len(diferencias) == 1
    diferencia = diferencias[0]
    assert diferencia.producto_id == producto_id
    assert diferencia.stock_en_hoja == 999
    assert diferencia.stock_recalculado == 5
    assert diferencia.diferencia == 999 - 5
