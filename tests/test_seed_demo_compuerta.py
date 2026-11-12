"""Compuerta de seguridad de los datos de demostración (§2 de la
continuación). Todo esto debe cumplirse SIEMPRE, sin excepción:

  a) scripts/seed_demo.py solo escribe en demo/OLATATA_DEMO.xlsx (nunca
     en OLATATA_DB.xlsx).
  b) Solo funciona con DEMO=1; sin esa variable, error claro y nada se
     escribe.
  c) Con DEMO=1 el almacenamiento queda en modo SOLO LOCAL: la
     publicación a GitHub está desactivada A NIVEL DE ALMACENAMIENTO
     (no solo "no se llama"), y cualquier intento de push lanza.
  d) Con DEMO=1 y "secrets" de GitHub presentes en el entorno, NINGUNA
     petición de red ocurre (mock que falla si hay una).
"""
from __future__ import annotations

import pytest

from core.storage import Storage
from scripts import seed_demo


def _boom(*_args, **_kwargs):
    raise AssertionError("no debería hacerse ninguna petición de red en modo demo")


# --------------------------------------------------------------- b) DEMO=1
def test_sin_demo_1_la_cli_termina_con_error_y_no_escribe_nada(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO", raising=False)
    destino = tmp_path / "demo" / "OLATATA_DEMO.xlsx"

    with pytest.raises(SystemExit):
        seed_demo.main(["--output", str(destino), "--dias", "1", "--ventas-por-dia", "2"])

    assert not destino.exists()


@pytest.mark.parametrize("valor", ["0", "true", "True", "si", ""])
def test_valores_distintos_de_1_tambien_bloquean(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("DEMO", valor)
    destino = tmp_path / "demo" / "OLATATA_DEMO.xlsx"

    with pytest.raises(SystemExit):
        seed_demo.main(["--output", str(destino), "--dias", "1", "--ventas-por-dia", "2"])

    assert not destino.exists()


# ------------------------------------------------------------- a) ruta
def test_nunca_se_permite_escribir_sobre_olatata_db_xlsx(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    destino = tmp_path / "OLATATA_DB.xlsx"

    with pytest.raises(SystemExit):
        seed_demo.main(["--output", str(destino), "--dias", "1", "--ventas-por-dia", "2"])

    assert not destino.exists()


def test_rechaza_el_nombre_prohibido_sin_importar_mayusculas_o_carpeta(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    destino = tmp_path / "cualquier" / "carpeta" / "OlaTata_DB.XLSX"

    with pytest.raises(SystemExit):
        seed_demo.main(["--output", str(destino), "--dias", "1", "--ventas-por-dia", "2"])

    assert not destino.exists()


# --------------------------------------------------- c) + d) solo local
def test_con_demo_1_y_secrets_de_github_presentes_no_hay_red_y_escribe_en_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    # Simula que los secrets de la app real están disponibles en la misma
    # máquina (lo normal en una laptop de desarrollo) — NO deben usarse.
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-de-produccion")
    monkeypatch.setenv("GITHUB_REPO", "GIUSEPPESAN21/OlaTata-Database")

    import core.storage as storage_mod

    monkeypatch.setattr(storage_mod.requests, "get", _boom)
    monkeypatch.setattr(storage_mod.requests, "put", _boom)

    destino = tmp_path / "demo" / "OLATATA_DEMO.xlsx"
    codigo = seed_demo.main(["--output", str(destino), "--dias", "1", "--ventas-por-dia", "2"])

    assert codigo == 0
    assert destino.exists()


def test_almacen_demo_solo_local_ignora_variables_de_entorno_de_github(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO", "fake/repo")

    storage = seed_demo._AlmacenDemoSoloLocal(tmp_path / "x.xlsx")

    assert storage.sync_enabled is False
    assert storage.github_repo is None
    assert storage.github_token is None


def test_almacen_demo_solo_local_lanza_si_alguna_vez_se_intenta_publicar(tmp_path):
    """Defensa en profundidad: aunque algo force `sync_enabled=True` más
    adelante (bug futuro), `_publish_to_github` sigue lanzando."""
    storage = seed_demo._AlmacenDemoSoloLocal(tmp_path / "x.xlsx")
    storage.sync_enabled = True  # simula el bug futuro a propósito

    with pytest.raises(RuntimeError, match="Modo demo"):
        storage._publish_to_github()


def test_almacen_demo_es_subclase_del_storage_real():
    assert issubclass(seed_demo._AlmacenDemoSoloLocal, Storage)
