"""Helpers de presentación puros (propiedad de A5 — SHELL/TEMA/AJUSTES).

Principio del encargo (§6): ningún cálculo de negocio vive aquí. Lo que
SÍ vive aquí es:
- Validación/generación de contraseñas para los formularios de usuario
  (la regla de mínimo 8 caracteres la exige §10 en la UI; bcrypt en
  `core.auth` no la impone).
- Formateo de fecha/hora local (Bogotá) para mostrar "última actividad".
- Generación de un código de incidente amable y registro del detalle
  real en el log del servidor (nunca una traza de Python visible al
  usuario, §6).
- Interpretación de `SyncStatus` en un texto/categoría amigable.
- Comparación de texto para confirmaciones de acciones destructivas.

Las funciones de CÁLCULO son puras y se pueden probar sin Streamlit
corriendo. Las que pintan algo (`tarjeta_kpi`, `estado_vacio`,
`pie_pagina`, `inyectar_identidad_visual`) importan `streamlit`
perezosamente (de forma local) para que este módulo siga siendo
importable en pruebas sin que Streamlit esté corriendo.
"""
from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.money import format_cop
from core.timeutil import BOGOTA, UTC

logger = logging.getLogger("olatata.ui")

__all__ = [
    "PASSWORD_MIN_LENGTH",
    "TOKENS",
    "validar_password",
    "generar_password_temporal",
    "generar_codigo_incidente",
    "registrar_error_servidor",
    "mensaje_error_amable",
    "formatear_fecha_hora_local",
    "resumen_estado_sync",
    "confirmacion_coincide",
    "tarjeta_kpi",
    "tarjeta_kpi_pesos",
    "estado_vacio",
    "pie_pagina",
    "inyectar_identidad_visual",
    "encabezado_pagina",
    "chip_estado",
    "render_logo",
    "logo_path",
    "plantilla_plotly_olatata",
    "registrar_tema_plotly",
]

PASSWORD_MIN_LENGTH = 8
_ALFABETO_PASSWORD_TEMPORAL = string.ascii_letters + string.digits

# --------------------------------------------------------------------
# TOKENS: única fuente de verdad de la paleta/tipografía/escala (C1-C3).
# Fijos por CLAUDE.md §8 y `tests/test_ui_theme.py` (colores de marca en
# `.streamlit/config.toml`) — este dict solo los expone para que el
# código Python (chips, plantilla Plotly, CSS inyectado) no repita los
# hex a mano en varios sitios.
# --------------------------------------------------------------------
TOKENS = {
    "color": {
        "primario": "#C2185B",
        "rosa_marca": "#FC7DA9",
        "rosa_veta": "#F8C0D8",
        "fondo": "#FDEFF0",
        "superficie": "#FFFFFF",
        "sidebar": "#FCE8EC",
        "dorado_bronce": "#A07838",
        "dorado_brillo": "#C09860",
        "dorado_texto": "#7A5A1F",
        "tinta": "#2B1B22",
        "texto_secundario": "#6B4A57",
        "exito": "#1E7E4F",
        "error": "#B3261E",
        "alerta_texto": "#8A5A00",
        "alerta_fondo": "#FFF4D6",
    },
    "tipografia": {
        "marca": "Great Vibes",
        "titulos": "Playfair Display",
        "interfaz": "Inter",
    },
    "escala_px": [14, 17, 20, 24, 29, 35, 42],
    "radio_px": 12,
}

# Orden de color para gráficas Plotly (C6): nunca más de 5 series.
_SECUENCIA_COLOR_PLOTLY = [
    TOKENS["color"]["primario"],
    TOKENS["color"]["dorado_brillo"],
    TOKENS["color"]["rosa_marca"],
    TOKENS["color"]["dorado_texto"],
    TOKENS["color"]["tinta"],
]

_ASSETS_DIR = None  # se resuelve perezosamente en logo_path()


def validar_password(password: str, minimo: int = PASSWORD_MIN_LENGTH) -> str | None:
    """Valida una contraseña nueva en el FORMULARIO (§10: bcrypt no impone
    largo mínimo, así que la UI debe hacerlo). Devuelve `None` si es
    válida, o un mensaje de error en español listo para mostrar."""
    if password is None or len(password) < minimo:
        return f"La contraseña debe tener al menos {minimo} caracteres."
    return None


def generar_password_temporal(longitud: int = 10) -> str:
    """Genera una clave temporal aleatoria (letras+dígitos) para el
    primer arranque o para restablecer la clave de un usuario."""
    longitud = max(longitud, PASSWORD_MIN_LENGTH)
    return "".join(secrets.choice(_ALFABETO_PASSWORD_TEMPORAL) for _ in range(longitud))


def generar_codigo_incidente() -> str:
    """Código corto y amigable para mostrar al usuario en caso de error,
    sin exponer nunca la traza real de Python (§6)."""
    return f"INC-{uuid.uuid4().hex[:8].upper()}"


def registrar_error_servidor(exc: BaseException, codigo: str, contexto: str = "") -> None:
    """El detalle real del error va SOLO al log del servidor, nunca a la
    pantalla. Sin datos personales en el mensaje (§10)."""
    logger.error("incidente=%s contexto=%s error=%r", codigo, contexto, exc, exc_info=True)


def mensaje_error_amable(exc: BaseException, contexto: str = "") -> tuple[str, str]:
    """Convierte cualquier excepción en un mensaje amable + código de
    incidente. Devuelve `(mensaje_para_el_usuario, codigo_incidente)`."""
    codigo = generar_codigo_incidente()
    registrar_error_servidor(exc, codigo, contexto)
    mensaje = (
        "Ocurrió un problema inesperado. "
        f"Código de incidente: {codigo}. Intenta de nuevo o avisa al administrador."
    )
    return mensaje, codigo


def formatear_fecha_hora_local(dt_utc: datetime) -> str:
    """Formatea un datetime UTC como fecha/hora de Bogotá legible (R2):
    "11/11/2026 08:30 a.m."."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    local = dt_utc.astimezone(BOGOTA)
    texto = local.strftime("%d/%m/%Y %I:%M %p")
    return texto.replace("AM", "a.m.").replace("PM", "p.m.")


def resumen_estado_sync(status: Any) -> dict[str, str]:
    """Interpreta un `SyncStatus` (duck-typed: `en_conflicto`,
    `pendientes`, `ultimo_error`, `ultimo_sync_utc`) en una categoría y
    texto amigables para Ajustes."""
    if getattr(status, "en_conflicto", False):
        return {
            "categoria": "error",
            "texto": "Hay un conflicto de sincronización sin resolver. Un admin debe elegir qué versión conservar.",
        }
    pendientes = getattr(status, "pendientes", 0)
    if pendientes:
        return {
            "categoria": "alerta",
            "texto": f"{pendientes} cambio(s) guardados localmente, pendientes de sincronizar.",
        }
    return {"categoria": "exito", "texto": "Todo sincronizado."}


def confirmacion_coincide(texto_esperado: str, texto_ingresado: str) -> bool:
    """Para confirmar una acción destructiva (§6): el usuario debe
    escribir de nuevo el nombre/usuario exacto (sin distinguir
    mayúsculas ni espacios externos)."""
    if texto_esperado is None or texto_ingresado is None:
        return False
    return texto_esperado.strip().lower() == texto_ingresado.strip().lower()


# --------------------------------------------------------------- pintado
def tarjeta_kpi(etiqueta: str, valor_formateado: str, delta: str | None = None) -> None:
    """Tarjeta KPI nativa de Streamlit (R1: `valor_formateado` ya debe
    venir de `core.money.format_cop` cuando sea dinero)."""
    import streamlit as st

    st.metric(label=etiqueta, value=valor_formateado, delta=delta)


def tarjeta_kpi_pesos(etiqueta: str, valor_pesos: int, delta: str | None = None) -> None:
    """Atajo: tarjeta KPI de un monto en pesos, formateado con R1."""
    tarjeta_kpi(etiqueta, format_cop(valor_pesos), delta)


def estado_vacio(mensaje: str, sugerencia: str | None = None) -> None:
    """Estado vacío que explica qué hacer (§6), nunca una pantalla en blanco."""
    import streamlit as st

    texto = mensaje if not sugerencia else f"{mensaje}\n\n{sugerencia}"
    st.info(texto)


def pie_pagina() -> None:
    import streamlit as st

    st.markdown(
        "<div style='text-align:center;color:#6B4A57;font-size:0.85rem;"
        "padding-top:1rem;'>Desarrollado por SAVA</div>",
        unsafe_allow_html=True,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def logo_path(nombre: str = "olatata-logo.png") -> str | None:
    """Ruta absoluta a un asset de `assets/brand/<nombre>`, o `None` si
    todavía no se generó con `scripts/build_logo_assets.py` (para que la
    app nunca truene si faltan los assets en un entorno nuevo)."""
    ruta = _repo_root() / "assets" / "brand" / nombre
    return str(ruta) if ruta.exists() else None


_IDENTIDAD_VISUAL_INYECTADA_KEY = "_ot_identidad_visual_inyectada"


def inyectar_identidad_visual() -> None:
    """Inyecta el CSS único del proyecto (`assets/theme.css`, C7) con
    selectores ESTABLES (`html`, `body`, `data-testid`) — nunca clases
    autogeneradas `.st-emotion-cache-*` (§9: esa es la falla real que se
    encontró en el repo de referencia Rapi Tienda). Las fuentes
    (Inter/Playfair Display/Great Vibes) se autoalojan vía
    `[[theme.fontFaces]]` en `.streamlit/config.toml` — este módulo solo
    aplica el resto del sistema de diseño (chips, tarjetas KPI, foco,
    reduced-motion, etc.).

    Idempotente dentro de una misma sesión de Streamlit: el CSS solo se
    reinyecta una vez por rerun para no duplicar el bloque `<style>`."""
    import streamlit as st

    try:
        css = (_repo_root() / "assets" / "theme.css").read_text(encoding="utf-8")
    except OSError:
        css = ""
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def encabezado_marca(nombre_negocio: str = "Ola Tata", *, contexto: str = "pantalla") -> None:
    """Cabecera de marca: logo circular + nombre en Great Vibes (A3/D1/D2).

    `contexto="pantalla"` (por defecto, usado por login y primer
    arranque): logo grande (180 px) centrado, pensado para una tarjeta
    central.
    `contexto="sidebar"`: avatar pequeño (72 px) + nombre en script al
    lado (A3: el texto de marca va en texto vivo, nunca dentro de la
    imagen) — pensado para la barra lateral.

    Si el logo aún no se generó (`scripts/build_logo_assets.py` no
    corrió en este entorno) se degrada a solo texto, sin tronar."""
    import streamlit as st

    inyectar_identidad_visual()
    ruta_logo = logo_path("olatata-logo.png") if contexto == "sidebar" else logo_path("olatata-logo-256.png")

    if contexto == "sidebar":
        if ruta_logo:
            import base64

            b64 = base64.b64encode(Path(ruta_logo).read_bytes()).decode("ascii")
            st.markdown(
                f"""
                <div class="ot-avatar-sidebar">
                    <img src="data:image/png;base64,{b64}" alt="Logo de {nombre_negocio}">
                    <span class="ot-marca-script">{nombre_negocio}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"<div class='ot-marca-script'>{nombre_negocio}</div>", unsafe_allow_html=True)
        return

    if ruta_logo:
        col_izq, col_centro, col_der = st.columns([1, 2, 1])
        with col_centro:
            st.image(ruta_logo, width=180, caption=None)
    st.markdown(
        f"<div class='ot-marca-script' style='text-align:center'>{nombre_negocio}</div>",
        unsafe_allow_html=True,
    )


def render_logo(tamano_px: int = 72, *, nombre_archivo: str = "olatata-logo.png", alt: str = "Logo de Ola Tata") -> None:
    """Pinta el logo circular a un tamaño dado, con texto alternativo
    (C8). A3: NUNCA estirar/deformar (se usa `width=`, que conserva la
    proporción 1:1 de un PNG ya cuadrado); por debajo de 56 px usa el
    derivado más pequeño disponible en vez de forzar el de 512 px."""
    import streamlit as st

    if tamano_px < 56 and nombre_archivo == "olatata-logo.png":
        nombre_archivo = "olatata-logo-64.png"
    ruta = logo_path(nombre_archivo)
    if ruta is None:
        return
    st.image(ruta, width=tamano_px)


def encabezado_pagina(titulo: str, subtitulo: str | None = None) -> None:
    """Encabezado de página (C5/D-todas): título en Playfair Display +
    subtítulo gris + filete dorado fino debajo. Sin acción principal
    embebida aquí a propósito: cada vista decide dónde poner su botón
    (p.ej. a la derecha con `st.columns`), este helper solo pinta el
    título/subtítulo/filete de forma consistente."""
    import streamlit as st

    inyectar_identidad_visual()
    subtitulo_html = (
        f"<p class='ot-encabezado-pagina__subtitulo'>{subtitulo}</p>" if subtitulo else ""
    )
    st.markdown(
        f"""
        <div class="ot-encabezado-pagina">
            <h1 class="ot-encabezado-pagina__titulo">{titulo}</h1>
            {subtitulo_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


_CHIP_ICONOS = {
    "exito": "check_circle",
    "alerta": "warning",
    "error": "cancel",
    "info": "info",
}


def chip_estado(texto: str, tipo: str = "info", *, icono: str | None = None) -> str:
    """Devuelve el HTML (listo para `st.markdown(..., unsafe_allow_html=True)`)
    de un chip de estado: icono + texto, NUNCA solo color (C5/C8 —
    "nada comunica solo por color"). `tipo` en {"exito","alerta","error","info"}.

    Pensado para que cualquier vista (p.ej. `views/inventario.py` para
    "En stock"/"Stock bajo"/"Agotado", o `views/vender.py` para
    "Anulada"/"Pendiente de sincronizar") lo use sin tener que repetir
    el marcado ni los colores."""
    tipo = tipo if tipo in _CHIP_ICONOS else "info"
    nombre_icono = icono or _CHIP_ICONOS[tipo]
    return (
        f'<span class="ot-chip ot-chip--{tipo}">'
        f'<span class="material-symbols-outlined" style="font-size:1rem">{nombre_icono}</span>'
        f"{texto}</span>"
    )


def plantilla_plotly_olatata() -> Any:
    """Construye (sin registrar globalmente) la plantilla Plotly
    "olatata" (C6): fuente Inter, fondo transparente, sin rejillas
    pesadas, colores en el orden de marca, ejes en $ sin decimales,
    `separators=",."` (formato colombiano: punto de miles, coma
    decimal). Devuelve el objeto `go.layout.Template` listo para usar
    como `fig.update_layout(template=plantilla_plotly_olatata())` — no
    depende de que `registrar_tema_plotly()` se haya llamado antes."""
    import plotly.graph_objects as go

    colores = TOKENS["color"]
    return go.layout.Template(
        layout=go.Layout(
            font=dict(family="Inter, sans-serif", color=colores["tinta"], size=13),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            colorway=_SECUENCIA_COLOR_PLOTLY,
            separators=",.",
            xaxis=dict(showgrid=False, zeroline=False, linecolor=colores["texto_secundario"]),
            yaxis=dict(
                showgrid=True,
                gridcolor="rgba(107,74,87,0.12)",
                zeroline=False,
                tickprefix="$ ",
                tickformat=",.0f",
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=40, r=20, t=40, b=40),
        )
    )


def registrar_tema_plotly() -> None:
    """Registra la plantilla "olatata" en `plotly.io.templates` bajo el
    nombre `"olatata"` y la deja como plantilla por defecto
    (`pio.templates.default`). Llamarla una vez (p.ej. al construir una
    gráfica) es suficiente — es idempotente. Pensado para que
    `views/analisis.py` (u otra vista con gráficas Plotly) solo haga:

        from core.ui import registrar_tema_plotly
        registrar_tema_plotly()
        fig = px.bar(..., template="olatata")
    """
    import plotly.io as pio

    pio.templates["olatata"] = plantilla_plotly_olatata()
    pio.templates.default = "olatata"
