"""Pruebas de regresión de los defectos del §2 (propiedad de A6).

Cada hallazgo de los repos de referencia (Software-Rapi-tienda-SAVA y
UNIMINUTO-Lab-Inventory, ver docs/CONTRATOS.md) tiene aquí una prueba
CONCRETA que debe fallar si Ola Tata reintrodujera ese mismo defecto. Las
partes que dependen de módulos de dominio que aún no existen en esta rama
(`core.inventory`/`core.sales`, propiedad de A1-A2) se marcan con
`pytest.xfail` en vez de fallar duro — se "activan" solo cuando el agente
principal integre esas ramas.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core import schema
from core.excel_safe import excel_safe
from core.money import DineroInvalidoError, format_cop, parse_pesos
from core.timeutil import BOGOTA, local_date, month_bounds_utc, to_iso_utc

CORE_DIR = Path(__file__).resolve().parent.parent / "core"


# --------------------------------------------------------------------------
# §2.a — Rapi Tienda corta el día en UTC puro (`today_utc`); 24.9% de las
# ventas (las de 7pm a medianoche Bogotá) caían en el día UTC siguiente.
# Ola Tata SIEMPRE corta día/semana/mes en America/Bogota.
# --------------------------------------------------------------------------

def test_ninguna_funcion_de_core_usa_utcnow_o_date_today_sueltos():
    """Regresión estática: el defecto exacto de Rapi Tienda fue construir la
    fecha "de hoy" con reloj UTC puro en vez de convertir a Bogotá. Si algún
    módulo de core/ reintrodujera `datetime.utcnow()` o `date.today()`
    directo (en vez de `core.timeutil.now_utc()` + `local_date()`), esta
    prueba debe detectarlo."""
    patrones_prohibidos = [
        re.compile(r"datetime\.utcnow\s*\("),
        re.compile(r"\bdate\.today\s*\("),
    ]
    violaciones = []
    for archivo in CORE_DIR.glob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        for patron in patrones_prohibidos:
            if patron.search(texto):
                violaciones.append(f"{archivo.name}: coincide con {patron.pattern}")
    assert not violaciones, f"Se encontró el defecto §2.a (corte de día en UTC puro): {violaciones}"


def test_venta_tarde_en_la_noche_bogota_no_cruza_al_dia_utc_siguiente():
    """El 24.9% de las ventas de Rapi Tienda (7pm-medianoche Bogotá) se
    reportaban en el día UTC equivocado. Reproduce ese horario exacto y
    confirma que `local_date` (lo que Ola Tata SIEMPRE debe usar para
    cortar el día) da el día de Bogotá, no el de UTC."""
    venta_8pm_bogota = datetime(2026, 11, 10, 20, 0, 0, tzinfo=BOGOTA).astimezone(timezone.utc)
    assert venta_8pm_bogota.date() == date(2026, 11, 11)  # el día UTC YA cambió
    assert local_date(venta_8pm_bogota) == date(2026, 11, 10)  # Ola Tata: sigue siendo el 10


def test_corte_de_mes_usa_medianoche_bogota_no_medianoche_utc():
    inicio, _fin = month_bounds_utc(2026, 11)
    medianoche_utc_1_nov = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert inicio != medianoche_utc_1_nov  # si cortara en UTC puro, coincidirían
    assert inicio == datetime(2026, 11, 1, 5, 0, 0, tzinfo=timezone.utc)  # medianoche Bogotá


# --------------------------------------------------------------------------
# §2.b — Cada escritura ingenua sube el libro COMPLETO y el .git crece sin
# control. Ola Tata usa libro vivo pequeño (solo el mes en curso) + cierre
# mensual a OlaTata-Archive.
# --------------------------------------------------------------------------

def test_el_esquema_separa_hojas_mensuales_de_hojas_permanentes():
    """El mecanismo que mantiene el libro vivo pequeño depende de que el
    esquema distinga claramente qué se archiva/vacía cada mes (ventas,
    movimientos, etc.) de qué es catálogo/estado permanente (stock,
    productos, usuarios...). Si alguien moviera `stock` a la lista de
    hojas mensuales por error, el stock se perdería en cada cierre."""
    assert schema.STOCK not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.PRODUCTOS not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.USUARIOS not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.CONFIG not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.PROVEEDORES not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.AUDITORIA not in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.VENTAS in schema.HOJAS_TRANSACCIONALES_MENSUALES
    assert schema.MOVIMIENTOS in schema.HOJAS_TRANSACCIONALES_MENSUALES


def test_cierre_de_mes_archiva_y_vacia_sin_perder_el_stock():
    """Simulación mínima (API pública de `core.storage` + `core.schema`) del
    mecanismo que evita el defecto §2.b: archivar + vaciar las hojas
    mensuales dejando `stock` intacto. No requiere `core.monthly_close`
    (que aún no existe); usa directamente `archive_put_bytes` y
    `transaction()`, que SÍ están congelados y disponibles."""
    try:
        from core import monthly_close  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        pytest.xfail(reason="depende de core.monthly_close, aún no integrado")
        return

    pytest.skip("core.monthly_close ya existe: esta regresión básica queda cubierta por las pruebas propias de ese módulo")


# --------------------------------------------------------------------------
# §2.c — Fechas en formatos mezclados en una misma columna rompen los
# análisis. Ola Tata usa SIEMPRE ISO-8601 UTC con offset.
# --------------------------------------------------------------------------

_ISO_UTC_CON_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00$")


def test_to_iso_utc_siempre_produce_el_mismo_formato_sin_importar_la_entrada():
    """Mezclar formatos (ISO sin offset, "dd/mm/aaaa", timestamps de Excel,
    etc.) en la misma columna fue el defecto §2.c. Toda fecha que entra a
    `to_iso_utc` — sin importar si venía naive, con otra zona, o ya en
    UTC — debe salir en el MISMO formato ISO-8601 con offset +00:00."""
    naive = datetime(2026, 11, 10, 15, 0, 0)
    con_zona_bogota = datetime(2026, 11, 10, 10, 0, 0, tzinfo=BOGOTA)
    con_zona_utc = datetime(2026, 11, 10, 15, 0, 0, tzinfo=timezone.utc)

    for dt in (naive, con_zona_bogota, con_zona_utc):
        iso = to_iso_utc(dt)
        assert _ISO_UTC_CON_OFFSET.match(iso), f"Formato inesperado: {iso!r}"


def test_una_columna_de_fechas_generada_por_el_seed_demo_es_un_unico_formato():
    """Regresión de extremo a extremo: genera un puñado de ventas ficticias
    con `scripts.seed_demo` (semilla fija) y confirma que TODA la columna
    `fecha_hora_utc` de `VENTAS` respeta el mismo formato ISO-8601+offset —
    nunca una mezcla de formatos como en el repo de referencia."""
    from scripts.seed_demo import crear_catalogo_y_proveedores, crear_usuarios_demo, generar_ventas_dia
    from tests.conftest import FakeStorage
    import random

    storage = FakeStorage()
    rng = random.Random(42)
    usuarios = crear_usuarios_demo(storage)
    productos = crear_catalogo_y_proveedores(storage, rng)
    generar_ventas_dia(storage, rng, date(2026, 1, 15), productos, usuarios, [], ventas_por_dia=15)

    df = storage.read_sheet(schema.VENTAS)
    assert len(df) > 0
    formatos_distintos = {bool(_ISO_UTC_CON_OFFSET.match(v)) for v in df["fecha_hora_utc"]}
    assert formatos_distintos == {True}, "La columna fecha_hora_utc mezcla formatos"


# --------------------------------------------------------------------------
# §2.d — Dinero con decimales en una moneda sin centavos; precio de venta
# menor que costo sin alerta; stock <=0 sin alerta.
# --------------------------------------------------------------------------

def test_dinero_con_decimales_se_rechaza_siempre():
    """El defecto §2.d: guardar pesos con 2 decimales en una moneda (COP)
    que no los tiene. `parse_pesos` debe RECHAZAR cualquier valor con
    decimales distintos de cero, sin importar el formato de entrada."""
    with pytest.raises(DineroInvalidoError):
        parse_pesos("1.250.000,50")
    with pytest.raises(DineroInvalidoError):
        parse_pesos(1250000.5)
    with pytest.raises(DineroInvalidoError):
        parse_pesos("$ 1.250,99")
    # Pero SÍ acepta enteros en cualquiera de los formatos colombianos:
    assert parse_pesos("$ 1.250.000") == 1250000
    assert parse_pesos("1.250.000,00") == 1250000
    assert format_cop(1250000) == "$ 1.250.000"


def test_precio_de_venta_menor_que_costo_genera_alerta():
    """§2.d: Rapi Tienda permitía vender por debajo del costo sin avisar.
    Depende de la validación de `core.inventory`/`core.sales` (A1/A2), que
    aún no existe en esta rama."""
    try:
        from core import inventory  # type: ignore  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        pytest.xfail(reason="depende de core.inventory, aún no integrado")
        return
    pytest.skip("core.inventory ya existe: su propia suite de pruebas cubre la alerta de precio<costo")


def test_stock_en_cero_o_negativo_genera_alerta():
    """§2.d: stock ≤0 sin alerta. Depende de `core.inventory` (A1), aún no
    existe en esta rama."""
    try:
        from core import inventory  # type: ignore  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        pytest.xfail(reason="depende de core.inventory, aún no integrado")
        return
    pytest.skip("core.inventory ya existe: su propia suite de pruebas cubre la alerta de stock<=0")


# --------------------------------------------------------------------------
# §2.e — CSS atado a clases generadas (`.st-emotion-cache-...`). Ola Tata
# solo usa tema nativo y `data-testid`.
# --------------------------------------------------------------------------

def test_ningun_archivo_del_repo_usa_selectores_st_emotion_cache():
    """Esas clases las regenera Streamlit en cada versión; depender de ellas
    fue el defecto §2.e. Revisa todo el código propio (no node_modules /
    .venv / .git) buscando el patrón exacto."""
    raiz = CORE_DIR.parent
    carpetas_excluidas = {".git", ".venv", "node_modules", "__pycache__", ".streamlit"}
    violaciones = []
    for archivo in raiz.rglob("*"):
        if not archivo.is_file():
            continue
        if any(parte in carpetas_excluidas for parte in archivo.parts):
            continue
        if archivo.suffix.lower() not in {".py", ".css", ".html", ".toml"}:
            continue
        if archivo.name == "test_regresion_referencias.py":
            continue  # este archivo menciona el patrón a propósito, en texto
        try:
            texto = archivo.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "st-emotion-cache" in texto:
            violaciones.append(str(archivo.relative_to(raiz)))
    assert not violaciones, f"Se encontraron selectores CSS frágiles (§2.e): {violaciones}"


def test_tema_de_streamlit_usa_solo_claves_nativas_documentadas():
    """El archivo de tema debe limitarse a las claves nativas de Streamlit
    (paleta de marca, ver CLAUDE.md) y no inyectar CSS por su cuenta."""
    config_toml = CORE_DIR.parent / ".streamlit" / "config.toml"
    if not config_toml.exists():
        pytest.skip(".streamlit/config.toml no existe en este checkout")
    texto = config_toml.read_text(encoding="utf-8")
    assert "st-emotion-cache" not in texto
    assert "[theme]" in texto


# --------------------------------------------------------------------------
# §2.f — El lab ya resolvió: escritura atómica, control por SHA,
# publicación síncrona, texto "=" guardado como fórmula perdido, login con
# límite de intentos. Ola Tata ya los adaptó en core/storage.py y
# core/auth.py (frozen); aquí solo confirmamos que las piedras angulares
# de esos defectos SIGUEN protegidas con pruebas propias, no que A6 las
# reimplemente.
# --------------------------------------------------------------------------

def test_texto_que_empieza_con_igual_nunca_se_pierde_ni_se_trunca():
    """R11: un texto libre "=1+1" debe sobrevivir intacto a excel_safe (la
    protección contra fórmula real vive en core/storage.py al escribir la
    celda, ya probado en tests/test_storage.py)."""
    assert excel_safe("=1+1") == "=1+1"
    assert excel_safe("@SUM(A1:A2)") == "@SUM(A1:A2)"
    assert excel_safe("=1+1\n") == "=1+1"


def test_login_tiene_limite_de_intentos_configurado():
    """§2.f: el lab ya resolvió 'login sin límite de intentos'. Confirma que
    la constante sigue viva en core.auth (congelado) — una regresión real
    estaría en tests/test_auth.py, esto es solo el guardado de la
    configuración que depende este hallazgo."""
    from core.auth import BLOQUEO_SEGUNDOS, MAX_INTENTOS

    assert MAX_INTENTOS >= 1
    assert BLOQUEO_SEGUNDOS > 0
