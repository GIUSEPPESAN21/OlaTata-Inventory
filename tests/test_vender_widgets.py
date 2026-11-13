"""Regresión (hallazgo de la prueba E2E por la interfaz): en Vender,
Streamlit ignora el `value=` de un widget con `key` que ya tiene estado,
así que los cambios hechos por el CÓDIGO al carrito/pagos se perdían:

- "Completar" dejaba el pago en $ 0 (no se podía
  cobrar sin escribir el monto a mano).
- Escanear otra vez el mismo producto no sumaba la cantidad.

Se ejecuta la vista real con `streamlit.testing.v1.AppTest` (sin navegador)
contra un `Storage` real en disco temporal.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _script(db_path: str) -> None:  # corre DENTRO de AppTest
    from core import auth, inventory
    from core.storage import Storage
    from views import ViewContext, vender

    import streamlit as st

    if "_storage" not in st.session_state:
        storage = Storage(local_path=db_path, sync_enabled=False)
        with storage.transaction() as tx:
            inventory.crear_producto(
                tx, "admin", nombre="Bolso Regresion", usuario_id="U-000001", categoria="Bolsos",
                costo=40000, precio=85000, codigo_barras="7700000000999", stock_inicial=10,
            )
        st.session_state["_storage"] = storage
    usuario = auth.Usuario(
        id="U-000001", nombre="Admin", usuario="admin", rol="admin", activo=True,
        must_change_password=False, session_epoch=1,
    )
    vender.render(ViewContext(storage=st.session_state["_storage"], usuario=usuario, rerun=st.rerun))


def _app(tmp_path) -> AppTest:
    at = AppTest.from_function(_script, args=(str(tmp_path / "OLATATA_DB.xlsx"),), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _agregar(at: AppTest, texto: str) -> None:
    """Escribe en el buscador en vivo. Un código exacto se agrega solo; un
    nombre muestra resultados y se pulsa "Agregar" en el primero."""
    antes = sum(linea["cantidad"] for linea in at.session_state["vender_carrito"]) if "vender_carrito" in at.session_state else 0
    at.text_input(key="vender_q").input(texto).run()
    assert not at.exception
    despues = sum(linea["cantidad"] for linea in at.session_state["vender_carrito"])
    if despues == antes:
        botones = [b for b in at.button if str(b.key or "").startswith("vender_add_")]
        if botones:
            botones[0].click().run()
            assert not at.exception


def _boton(at: AppTest, etiqueta: str):
    return next(b for b in at.button if b.label == etiqueta)


def test_completar_con_el_total_restante_llena_el_monto_del_pago(tmp_path):
    at = _app(tmp_path)
    _agregar(at, "Bolso Regresion")
    _boton(at, "Completar").click().run()
    assert at.number_input(key="vender_pago_monto_0").value == 85000
    assert _boton(at, "Cobrar").disabled is False


def test_escanear_dos_veces_el_mismo_producto_suma_la_cantidad(tmp_path):
    at = _app(tmp_path)
    _agregar(at, "7700000000999")
    _agregar(at, "7700000000999")
    assert at.number_input(key="vender_cant_0").value == 2
    assert at.session_state["vender_carrito"][0]["cantidad"] == 2


def test_venta_completa_por_la_vista_descuenta_stock(tmp_path):
    at = _app(tmp_path)
    _agregar(at, "Bolso Regresion")
    _boton(at, "Completar").click().run()
    _boton(at, "Cobrar").click().run()
    assert not at.exception
    assert at.session_state["vender_recibo"] is not None
    storage = at.session_state["_storage"]
    from core import schema

    stock = storage.read_sheet(schema.STOCK)
    assert int(stock.iloc[0]["cantidad"]) == 9


def test_lector_usb_codigo_interno_de_etiqueta_y_teclado_latino(tmp_path):
    """El lector "teclea": el código interno de la etiqueta (20000001) y el
    id con el guion convertido en apóstrofo por el teclado latinoamericano
    (OT'000001) deben encontrar el mismo producto."""
    at = _app(tmp_path)
    _agregar(at, "20000001")
    _agregar(at, "ot'000001")
    assert at.session_state["vender_carrito"][0]["cantidad"] == 2
    _agregar(at, "99999999")
    assert any("Ningún producto coincide" in m.value for m in at.markdown)
    assert at.session_state["vender_carrito"][0]["cantidad"] == 2  # nada raro se agregó


def test_busqueda_en_vivo_muestra_resultados_y_codigo_limpia_el_campo(tmp_path):
    at = _app(tmp_path)
    at.text_input(key="vender_q").input("regres").run()  # parte del nombre, sin Enter
    assert [b.key for b in at.button if str(b.key or "").startswith("vender_add_")] == ["vender_add_OT-000001"]
    assert at.session_state["vender_carrito"] == []  # un nombre NO se agrega solo
    at.text_input(key="vender_q").input("7700000000999").run()  # el lector: código exacto
    assert at.session_state["vender_carrito"][0]["cantidad"] == 1
    assert at.text_input(key="vender_q").value == ""  # listo para el siguiente escaneo
