"""Regresión del incidente INC-FC2998BE (pestaña "Mes" de Análisis).

Causa raíz: `st.plotly_chart` / `st.dataframe` SIN `key` en
`views/analisis.py`. Streamlit deriva el ID interno de cada elemento de
sus parámetros; cuando dos pestañas producen elementos idénticos (p.ej.
figuras VACÍAS en un mes sin ventas, o el mismo Top 10 cuando
hoy == semana == mes), el segundo lanza `StreamlitDuplicateElementId` y
`app.py` lo convierte en el error amable con código de incidente.

El modo "bare" (llamar las funciones de la vista fuera de Streamlit) NO
detecta esto porque el registro de IDs vive en el `ScriptRunContext`;
por eso esta prueba usa `streamlit.testing.v1.AppTest`, que ejecuta la
vista con un contexto de ejecución real.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _script_analisis(ruta_db: Path) -> str:
    return f"""
import sys, types
sys.path.insert(0, {str(REPO_ROOT)!r})
from core.storage import Storage
from views import analisis

storage = Storage(local_path={str(ruta_db)!r}, sync_enabled=False)
usuario = types.SimpleNamespace(id="U-000001", rol="admin", nombre="Admin Demo")
ctx = types.SimpleNamespace(storage=storage, usuario=usuario, rerun=lambda: None)
analisis.render(ctx)
"""


@pytest.fixture(scope="module")
def ruta_db_demo(tmp_path_factory) -> Path:
    """Libro real en disco con datos demo cuyo "hoy" (fecha real de la
    corrida) cae en un mes SIN ventas — el caso que dispara elementos
    idénticos (vacíos) en Hoy/Semana/Mes a la vez."""
    from core.storage import Storage
    from scripts.seed_demo import poblar_demo

    ruta = tmp_path_factory.mktemp("analisis_dup") / "DEMO.xlsx"
    storage = Storage(local_path=ruta, sync_enabled=False)
    poblar_demo(storage, dias=10, ventas_por_dia=5, fecha_inicio=date(2025, 9, 1))
    return ruta


def test_analisis_renderiza_sin_excepcion_con_mes_vacio(ruta_db_demo):
    at = AppTest.from_string(_script_analisis(ruta_db_demo), default_timeout=180)
    at.run()
    detalles = [f"{e.type}: {e.message}" for e in at.exception]
    assert not at.exception, f"La vista Análisis lanzó excepción(es): {detalles}"


def test_todo_plotly_chart_y_dataframe_de_analisis_llevan_key():
    """Guarda estática adicional: cada `st.plotly_chart(` y
    `st.dataframe(` de views/analisis.py debe llevar `key=` en la misma
    llamada, para que un elemento nuevo sin key no reintroduzca el bug
    en un estado de datos que la prueba dinámica no cubra."""
    import re

    texto = (REPO_ROOT / "views" / "analisis.py").read_text(encoding="utf-8")
    sin_key = []
    for m in re.finditer(r"st\.(plotly_chart|dataframe)\(", texto):
        # Captura hasta el cierre del paréntesis balanceado de la llamada.
        inicio = m.end() - 1
        nivel, fin = 0, inicio
        for i in range(inicio, len(texto)):
            if texto[i] == "(":
                nivel += 1
            elif texto[i] == ")":
                nivel -= 1
                if nivel == 0:
                    fin = i
                    break
        llamada = texto[m.start() : fin + 1]
        if "key=" not in llamada:
            linea = texto[: m.start()].count("\n") + 1
            sin_key.append(f"línea {linea}: {llamada[:60]}...")
    assert not sin_key, f"Llamadas sin key= en views/analisis.py: {sin_key}"
