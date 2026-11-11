import threading
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core import schema
from core.storage import Storage


def _nueva_storage(tmp_path, **kwargs):
    return Storage(local_path=tmp_path / "OLATATA_DB.xlsx", sync_enabled=False, **kwargs)


def test_libro_nuevo_tiene_todas_las_hojas_vacias(tmp_path):
    st = _nueva_storage(tmp_path)
    for name in schema.SHEET_NAMES:
        df = st.read_sheet(name)
        assert list(df.columns) == schema.columnas(name)
        assert len(df) == 0


def test_write_sheet_fuera_de_transaccion_lanza(tmp_path):
    st = _nueva_storage(tmp_path)
    df = st.read_sheet(schema.PROVEEDORES)
    with pytest.raises(RuntimeError):
        st.write_sheet(schema.PROVEEDORES, df)


def test_transaccion_persiste_a_disco_de_forma_atomica(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        df = tx.read_sheet(schema.PROVEEDORES)
        nueva = pd.DataFrame(
            [{"id": "P-1", "nombre": "Proveedor X", "telefono": "3001234567", "ciudad": "Buga", "notas": "", "created_at": "", "updated_at": ""}]
        )
        tx.write_sheet(schema.PROVEEDORES, pd.concat([df, nueva], ignore_index=True))
    assert st.local_path.exists()

    st2 = _nueva_storage(tmp_path)
    st2.local_path = st.local_path
    df_leido = st2.read_sheet(schema.PROVEEDORES)
    assert len(df_leido) == 1
    assert df_leido.iloc[0]["nombre"] == "Proveedor X"


def test_excepcion_dentro_de_transaccion_no_deja_nada_a_medias(tmp_path):
    st = _nueva_storage(tmp_path)
    with pytest.raises(ValueError):
        with st.transaction() as tx:
            df = tx.read_sheet(schema.PROVEEDORES)
            nueva = pd.DataFrame([{"id": "P-1", "nombre": "X", "telefono": "", "ciudad": "", "notas": "", "created_at": "", "updated_at": ""}])
            tx.write_sheet(schema.PROVEEDORES, pd.concat([df, nueva], ignore_index=True))
            raise ValueError("algo salió mal a mitad de la transacción")
    assert not st.local_path.exists()  # nunca se persistió nada
    assert len(st.read_sheet(schema.PROVEEDORES)) == 0  # tampoco quedó en memoria


def test_backup_bak_se_crea_en_la_segunda_escritura(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        tx.set_config("x", "1")
    assert not st.local_path.with_suffix(".bak").exists()
    with st.transaction() as tx:
        tx.set_config("x", "2")
    assert st.local_path.with_suffix(".bak").exists()


def test_texto_que_empieza_con_igual_nunca_se_guarda_como_formula(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        df = tx.read_sheet(schema.PROVEEDORES)
        nueva = pd.DataFrame(
            [{"id": "P-1", "nombre": "=1+1", "telefono": "", "ciudad": "", "notas": "@SUM(1)", "created_at": "", "updated_at": ""}]
        )
        tx.write_sheet(schema.PROVEEDORES, pd.concat([df, nueva], ignore_index=True))

    st2 = Storage(local_path=st.local_path, sync_enabled=False)
    df_leido = st2.read_sheet(schema.PROVEEDORES)
    assert df_leido.iloc[0]["nombre"] == "=1+1"
    assert df_leido.iloc[0]["notas"] == "@SUM(1)"


def test_booleanos_sobreviven_el_round_trip(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        df = tx.read_sheet(schema.PRODUCTOS)
        nueva = pd.DataFrame(
            [
                {
                    "id": "OT-000001",
                    "nombre": "Bolso",
                    "categoria": "Bolsos",
                    "color": "Negro",
                    "talla_tamano": "",
                    "proveedor_id": "",
                    "costo": 50000,
                    "precio": 90000,
                    "stock_minimo": 2,
                    "codigo_barras": "",
                    "activo": True,
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
        tx.write_sheet(schema.PRODUCTOS, pd.concat([df, nueva], ignore_index=True))

    st2 = Storage(local_path=st.local_path, sync_enabled=False)
    df_leido = st2.read_sheet(schema.PRODUCTOS)
    assert bool(df_leido.iloc[0]["activo"]) is True


def test_next_counter_incrementa_y_persiste(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        a = tx.next_counter("productos")
    with st.transaction() as tx:
        b = tx.next_counter("productos")
    assert a == 1
    assert b == 2


def test_next_counter_con_reset_key_independiente(tmp_path):
    st = _nueva_storage(tmp_path)
    with st.transaction() as tx:
        a = tx.next_counter("ventas", reset_key="2026-11")
        b = tx.next_counter("ventas", reset_key="2026-12")
    assert a == 1
    assert b == 1  # reinicia por mes, numeración independiente


def test_lock_serializa_20_hilos_incrementando_el_mismo_contador(tmp_path):
    st = _nueva_storage(tmp_path)
    errores = []

    def incrementar():
        try:
            with st.transaction() as tx:
                tx.next_counter("stress")
        except Exception as exc:  # pragma: no cover - solo si algo va mal
            errores.append(exc)

    hilos = [threading.Thread(target=incrementar) for _ in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)

    assert not errores
    assert not any(h.is_alive() for h in hilos)
    valor_final = int(st.get_config("contador::stress::global"))
    assert valor_final == 20  # ninguna escritura se perdió por la carrera


# ------------------------------------------------------- publicación GitHub

def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400 and status_code not in (404, 409, 422):
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def test_publish_exitoso_primera_vez_sin_sha_previo(tmp_path):
    st = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="x/y", github_token="t", sync_enabled=True)
    with patch("core.storage.requests.get", return_value=_mock_response(404)) as mget, patch(
        "core.storage.requests.put", return_value=_mock_response(200, {"content": {"sha": "sha-nuevo"}})
    ) as mput:
        with st.transaction() as tx:
            tx.set_config("a", "1")
    assert mget.called and mput.called
    estado = st.sync_status()
    assert estado.pendientes == 0
    assert not estado.en_conflicto


def test_publish_detecta_conflicto_real_y_no_sobrescribe(tmp_path):
    st = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="x/y", github_token="t", sync_enabled=True)
    with patch("core.storage.requests.get", return_value=_mock_response(404)), patch(
        "core.storage.requests.put", return_value=_mock_response(200, {"content": {"sha": "sha-1"}})
    ):
        with st.transaction() as tx:
            tx.set_config("a", "1")

    # Alguien más cambió el archivo remoto: ahora el sha real es distinto al conocido.
    with patch("core.storage.requests.get", return_value=_mock_response(200, {"sha": "sha-OTRO"})), patch(
        "core.storage.requests.put"
    ) as mput:
        with st.transaction() as tx:
            tx.set_config("a", "2")
    assert not mput.called  # NUNCA se intenta sobrescribir sin resolver el conflicto
    estado = st.sync_status()
    assert estado.en_conflicto is True
    assert estado.pendientes >= 1


def test_red_caida_no_pierde_la_venta_solo_marca_pendiente(tmp_path):
    st = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="x/y", github_token="t", sync_enabled=True)
    with patch("core.storage.requests.get", side_effect=ConnectionError("sin red")):
        with st.transaction() as tx:
            tx.set_config("a", "1")
    # El dato SI quedó guardado localmente, aunque la nube no respondió.
    assert st.get_config("a") == "1"
    estado = st.sync_status()
    assert estado.pendientes >= 1
    assert estado.ultimo_error is not None


def test_reintento_ante_409_transitorio_termina_en_exito(tmp_path):
    st = Storage(local_path=tmp_path / "OLATATA_DB.xlsx", github_repo="x/y", github_token="t", sync_enabled=True)
    respuestas_put = [_mock_response(409), _mock_response(200, {"content": {"sha": "sha-final"}})]
    with patch("core.storage.requests.get", return_value=_mock_response(404)), patch(
        "core.storage.requests.put", side_effect=respuestas_put
    ):
        with st.transaction() as tx:
            tx.set_config("a", "1")
    estado = st.sync_status()
    assert estado.pendientes == 0
    assert not estado.en_conflicto
