"""Carga de la base desde la nube (OlaTata-Database) y resolución de
conflictos. Usa un GitHub simulado en memoria (sin red real).

Regresión del hallazgo crítico: en Streamlit Cloud el disco es efímero y
`Storage` solo leía el archivo local; tras cada reinicio arrancaba con un
libro vacío y la primera transacción SOBRESCRIBÍA la base real (así se
perdieron las 12 claves de configuración del negocio en producción).
"""
from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch

import pandas as pd
import pytest

from core import schema
from core.permissions import PermisoDenegadoError
from core.sincronizacion import (
    OPCION_CONSERVAR_LOCAL,
    OPCION_USAR_NUBE,
    estado_conexion,
    resolver_conflicto,
    sincronizar_ahora,
)
from core.storage import BaseDeDatosNoDisponibleError, Storage

REPO = "dueno/OlaTata-Database"
ARCHIVO = "OLATATA_DB.xlsx"


class _Resp:
    def __init__(self, status_code=200, data=None, content=b""):
        self.status_code = status_code
        self._data = data or {}
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class GitHubFalso:
    """Imita la API de contenidos: GET (JSON o crudo) y PUT con control de sha."""

    def __init__(self, *, limite_base64: int = 1_000_000):
        self.archivos: dict[str, tuple[bytes, str]] = {}
        self.sin_red = False
        self.limite_base64 = limite_base64
        self.puts = 0

    def _ruta(self, url: str) -> str:
        return url.split("/contents/", 1)[1]

    def subir(self, ruta: str, contenido: bytes) -> str:
        sha = hashlib.sha1(contenido + str(len(self.archivos) + self.puts).encode()).hexdigest()
        self.archivos[ruta] = (contenido, sha)
        return sha

    def get(self, url, headers=None, timeout=None):
        if self.sin_red:
            raise ConnectionError("sin red (simulado)")
        ruta = self._ruta(url)
        if ruta not in self.archivos:
            return _Resp(404)
        contenido, sha = self.archivos[ruta]
        if (headers or {}).get("Accept") == "application/vnd.github.raw":
            return _Resp(200, content=contenido)
        if len(contenido) > self.limite_base64:
            return _Resp(200, {"sha": sha, "encoding": "none", "content": ""})
        return _Resp(200, {"sha": sha, "encoding": "base64", "content": base64.b64encode(contenido).decode()})

    def put(self, url, headers=None, json=None, timeout=None):
        if self.sin_red:
            raise ConnectionError("sin red (simulado)")
        ruta = self._ruta(url)
        actual = self.archivos.get(ruta)
        if actual is not None and json.get("sha") != actual[1]:
            return _Resp(409)
        self.puts += 1
        sha = self.subir(ruta, base64.b64decode(json["content"]))
        return _Resp(200, {"content": {"sha": sha}})

    def libro(self, ruta: str = ARCHIVO) -> dict[str, pd.DataFrame]:
        import io

        return pd.read_excel(io.BytesIO(self.archivos[ruta][0]), sheet_name=None, dtype=object)


@pytest.fixture
def gh():
    falso = GitHubFalso()
    with patch("core.storage.requests.get", side_effect=falso.get), patch(
        "core.storage.requests.put", side_effect=falso.put
    ):
        yield falso


def _storage(path, **kw) -> Storage:
    return Storage(local_path=path, github_repo=REPO, github_token="t", archive_repo="dueno/Archive", sync_enabled=True, **kw)


def _libro_con_admin(tmp_path) -> bytes:
    """Construye un libro real (como el que hay hoy en producción)."""
    origen = Storage(local_path=tmp_path / "origen" / ARCHIVO, sync_enabled=False)
    origen.local_path.parent.mkdir(parents=True, exist_ok=True)
    with origen.transaction() as tx:
        df = tx.read_sheet(schema.USUARIOS)
        fila = {c: "" for c in schema.columnas(schema.USUARIOS)}
        fila.update(id="U-000001", nombre="Admin", usuario="admin", rol="admin", activo=True,
                    must_change_password=False, session_epoch=1)
        tx.write_sheet(schema.USUARIOS, pd.concat([df, pd.DataFrame([fila])], ignore_index=True))
        tx.set_config("negocio_nombre", "Ola Tata")
    return origen.local_path.read_bytes()


# ------------------------------------------------------------------ carga
def test_servidor_nuevo_sin_archivo_local_descarga_la_base_de_la_nube(tmp_path, gh):
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    st = _storage(tmp_path / "srv" / ARCHIVO)
    usuarios = st.read_sheet(schema.USUARIOS)
    assert list(usuarios["usuario"]) == ["admin"]
    assert st.get_config("negocio_nombre") == "Ola Tata"
    assert st.local_path.exists()  # quedó copia local para trabajar


def test_regresion_reinicio_no_sobrescribe_los_datos_de_la_nube(tmp_path, gh):
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    st = _storage(tmp_path / "srv" / ARCHIVO)
    with st.transaction() as tx:
        tx.set_config("sesion_minutos", "480")
    publicado = gh.libro()
    assert list(publicado["usuarios"]["usuario"]) == ["admin"]  # el admin sigue ahí
    config = dict(zip(publicado["config"]["clave"], publicado["config"]["valor"]))
    assert config["negocio_nombre"] == "Ola Tata"
    assert str(config["sesion_minutos"]) == "480"
    assert st.sync_status().pendientes == 0 and not st.sync_status().en_conflicto


def test_base_mayor_a_1mb_se_descarga_en_crudo(tmp_path):
    falso = GitHubFalso(limite_base64=10)  # fuerza la ruta de "archivo grande"
    with patch("core.storage.requests.get", side_effect=falso.get), patch(
        "core.storage.requests.put", side_effect=falso.put
    ):
        falso.subir(ARCHIVO, _libro_con_admin(tmp_path))
        st = _storage(tmp_path / "srv" / ARCHIVO)
        assert list(st.read_sheet(schema.USUARIOS)["usuario"]) == ["admin"]


def test_base_nueva_en_la_nube_404_arranca_vacia_y_publica(tmp_path, gh):
    st = _storage(tmp_path / ARCHIVO)
    assert st.read_sheet(schema.USUARIOS).empty
    with st.transaction() as tx:
        tx.set_config("a", "1")
    assert ARCHIVO in gh.archivos


def test_sin_red_y_sin_copia_local_no_arranca_vacia(tmp_path, gh):
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    gh.sin_red = True
    st = _storage(tmp_path / "srv" / ARCHIVO)
    with pytest.raises(BaseDeDatosNoDisponibleError):
        st.read_sheet(schema.USUARIOS)
    with pytest.raises(BaseDeDatosNoDisponibleError):
        with st.transaction():
            pass
    # Vuelve la red: el mismo objeto se recupera solo (no quedó "cargado vacío").
    gh.sin_red = False
    assert list(st.read_sheet(schema.USUARIOS)["usuario"]) == ["admin"]


def test_sin_red_con_copia_local_trabaja_offline_y_luego_detecta_conflicto(tmp_path, gh):
    ruta = tmp_path / "srv" / ARCHIVO
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    _storage(ruta).read_sheet(schema.USUARIOS)  # primera carga deja copia + sidecar

    gh.sin_red = True
    st = _storage(ruta)
    assert list(st.read_sheet(schema.USUARIOS)["usuario"]) == ["admin"]
    assert st.sync_status().ultimo_error
    with st.transaction() as tx:
        tx.set_config("offline", "si")
    assert st.sync_status().pendientes >= 1

    # Mientras tanto, alguien cambió la nube: NUNCA se sobrescribe.
    gh.sin_red = False
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path / "otro"))
    puts_antes = gh.puts
    estado = st.sincronizar_ahora()
    assert estado.en_conflicto is True
    assert gh.puts == puts_antes


def test_cambios_locales_pendientes_sobre_la_misma_version_se_conservan(tmp_path, gh):
    ruta = tmp_path / "srv" / ARCHIVO
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    st = _storage(ruta)
    st.read_sheet(schema.CONFIG)  # abrió con red
    gh.sin_red = True
    with st.transaction() as tx:
        tx.set_config("venta_offline", "1")
    gh.sin_red = False

    # Reinicio del proceso (misma máquina): la copia local con cambios
    # pendientes se conserva y se publica (avance rápido, sin conflicto).
    st2 = _storage(ruta)
    assert st2.get_config("venta_offline") == "1"
    estado = st2.sincronizar_ahora()
    assert estado.pendientes == 0 and not estado.en_conflicto
    config = gh.libro()["config"]
    assert "venta_offline" in set(config["clave"])


def test_copia_local_vieja_se_respalda_y_gana_la_nube(tmp_path, gh):
    ruta = tmp_path / "srv" / ARCHIVO
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(_libro_con_admin(tmp_path / "vieja"))
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path / "nube"))
    # Modifica la copia de la nube para que difiera de la local.
    st_tmp = Storage(local_path=tmp_path / "x" / ARCHIVO, sync_enabled=False)
    st_tmp.local_path.parent.mkdir(parents=True)
    st_tmp.local_path.write_bytes(gh.archivos[ARCHIVO][0])
    with st_tmp.transaction() as tx:
        tx.set_config("solo_en_la_nube", "1")
    gh.subir(ARCHIVO, st_tmp.local_path.read_bytes())

    st = _storage(ruta)
    assert st.get_config("solo_en_la_nube") == "1"
    respaldos = list(ruta.parent.glob("OLATATA_DB.local-*.xlsx"))
    assert len(respaldos) == 1


def test_nunca_publica_a_ciegas_sobre_una_base_remota_desconocida(tmp_path, gh):
    st = _storage(tmp_path / ARCHIVO)
    st.read_sheet(schema.CONFIG)  # la nube estaba vacía (404) al abrir
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))  # aparece una base después
    with st.transaction() as tx:
        tx.set_config("a", "1")
    assert st.sync_status().en_conflicto is True
    assert list(gh.libro()["usuarios"]["usuario"]) == ["admin"]  # intacta


# ---------------------------------------------------------- resolución
def _provocar_conflicto(tmp_path, gh) -> Storage:
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path))
    st = _storage(tmp_path / "srv" / ARCHIVO)
    st.read_sheet(schema.CONFIG)
    gh.subir(ARCHIVO, _libro_con_admin(tmp_path / "otro"))  # alguien cambió la nube
    with st.transaction() as tx:
        tx.set_config("mio", "local")
    assert st.sync_status().en_conflicto
    return st


def test_resolver_usando_la_nube_recarga_y_respalda_la_local(tmp_path, gh):
    st = _provocar_conflicto(tmp_path, gh)
    estado = resolver_conflicto(st, "admin", OPCION_USAR_NUBE)
    assert not estado.en_conflicto
    assert st.get_config("mio") is None  # se descartó lo local...
    assert list(st.local_path.parent.glob("OLATATA_DB.conflicto-*.xlsx"))  # ...pero quedó respaldado


def test_resolver_conservando_lo_local_publica_y_limpia_el_conflicto(tmp_path, gh):
    st = _provocar_conflicto(tmp_path, gh)
    estado = resolver_conflicto(st, "admin", OPCION_CONSERVAR_LOCAL)
    assert not estado.en_conflicto and estado.pendientes == 0
    config = gh.libro()["config"]
    assert "mio" in set(config["clave"])


def test_resolver_conflicto_exige_permiso_y_opcion_valida(tmp_path, gh):
    st = _provocar_conflicto(tmp_path, gh)
    with pytest.raises(PermisoDenegadoError):
        resolver_conflicto(st, "vendedor", OPCION_USAR_NUBE)
    with pytest.raises(PermisoDenegadoError):
        sincronizar_ahora(st, "vendedor")
    with pytest.raises(ValueError):
        resolver_conflicto(st, "admin", "las-dos")


def test_sincronizar_ahora_publica_pendientes_tras_caida_de_red(tmp_path, gh):
    st = _storage(tmp_path / ARCHIVO)
    st.read_sheet(schema.CONFIG)
    gh.sin_red = True
    with st.transaction() as tx:
        tx.set_config("a", "1")
    assert st.sync_status().pendientes >= 1
    gh.sin_red = False
    estado = sincronizar_ahora(st, "admin")
    assert estado.pendientes == 0 and estado.ultimo_error is None


def test_estado_conexion_describe_nube_y_local(tmp_path, gh):
    st = _storage(tmp_path / ARCHIVO)
    e = estado_conexion(st)
    assert e.modo == "nube" and e.repositorio == REPO
    local = Storage(local_path=tmp_path / "l.xlsx", sync_enabled=False)
    e2 = estado_conexion(local)
    assert e2.modo == "local" and e2.repositorio is None


def test_sin_sync_las_operaciones_de_nube_no_hacen_nada(tmp_path):
    st = Storage(local_path=tmp_path / ARCHIVO, sync_enabled=False)
    assert st.sincronizar_ahora().en_conflicto is False
    assert st.resolver_conflicto_conservar_local().en_conflicto is False


def test_archive_get_bytes_descarga_del_repo_de_archivo(tmp_path, gh):
    gh.subir("cierres/2026-10.xlsx", b"contenido-archivado")
    st = _storage(tmp_path / ARCHIVO)
    assert st.archive_get_bytes("cierres/2026-10.xlsx") == b"contenido-archivado"
    assert st.archive_get_bytes("cierres/no-existe.xlsx") is None
