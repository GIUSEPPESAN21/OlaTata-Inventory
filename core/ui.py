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

import itertools
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from core.money import format_cop
from core.timeutil import BOGOTA, UTC

logger = logging.getLogger("olatata.ui")

__all__ = [
    "PASSWORD_MIN_LENGTH",
    "TOKENS",
    "ICONOS_VISTA",
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
    "kpi_card",
    "estado_vacio",
    "empty_state",
    "pie_pagina",
    "inyectar_identidad_visual",
    "reiniciar_identidad_visual_para_este_rerun",
    "page_background",
    "brand_rings_svg",
    "brand_rings",
    "encabezado_pagina",
    "hero",
    "titulo_seccion",
    "card",
    "chip_estado",
    "chip",
    "icono_md",
    "render_logo",
    "logo_path",
    "plantilla_plotly_olatata",
    "registrar_tema_plotly",
    "ETIQUETAS_COLUMNAS",
    "tabla_amigable",
    "boton_imprimir_pdf",
    "enfocar_campo",
    "guia",
    "md_seguro",
]

# Iconos Material Symbols (§9: sin emojis en la UI) para cada vista del
# menú lateral. `views/__init__.py` es contrato congelado (trae un emoji
# en `icon`, pensado para el encargo original) — en vez de tocarlo, A5
# mapea aquí la MISMA clave `vista["key"]` a un icono Material, y
# `app.py` usa este diccionario en vez de `vista["icon"]` al construir la
# navegación lateral (ver informe final de A5 sobre este hallazgo)."""
ICONOS_VISTA = {
    "vender": "shopping_bag",
    "ventas": "receipt_long",
    "inventario": "inventory_2",
    "analisis": "bar_chart",
    "ajustes": "settings",
}

PASSWORD_MIN_LENGTH = 10  # ver core.seguridad.PASSWORD_MIN

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


def validar_password(password: str, *, usuario: str | None = None, nombre: str | None = None) -> str | None:
    """Valida una contraseña nueva en el FORMULARIO con la política de
    `core.seguridad.evaluar_password` (mínimo 10, letras y números, no
    común, sin el usuario/nombre). `None` si es válida; si no, el motivo."""
    from core.seguridad import evaluar_password

    return evaluar_password(password, usuario=usuario, nombre=nombre)


def generar_password_temporal(longitud: int = 12) -> str:
    """Clave temporal aleatoria que siempre cumple la política (primer
    arranque, crear usuario, restablecer clave)."""
    from core.seguridad import generar_password_temporal as _generar

    return _generar(longitud)


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


def icono_md(nombre: str, *, tamano_px: int = 20, color: str | None = None) -> str:
    """HTML de un icono Material Symbols autoalojado (§9: sin emojis),
    listo para incrustar en cualquier bloque propio con
    `unsafe_allow_html=True`. Para widgets NATIVOS de Streamlit (botones,
    markdown de texto) se prefiere el atajo incorporado `:material/nombre:`
    en vez de esta función — `icono_md` es solo para el marcado propio
    (tarjetas, chips, encabezados) donde se escribe el HTML a mano."""
    estilo = f"font-size:{tamano_px}px;line-height:1;"
    if color:
        estilo += f"color:{color};"
    return f'<span class="material-symbols-outlined" style="{estilo}">{nombre}</span>'


def estado_vacio(mensaje: str, sugerencia: str | None = None, *, icono: str = "search_off") -> None:
    """Estado vacío premium (§6/D-todas): tarjeta con el motivo de aros muy
    tenue detrás de un icono, mensaje cálido y sugerencia opcional —
    nunca una pantalla en blanco ni un `st.info` plano. Mismo contrato de
    llamada que la versión anterior (mensaje + sugerencia opcionales),
    así ninguna vista que ya la use necesita cambiar su llamada."""
    import streamlit as st

    inyectar_identidad_visual()
    sugerencia_html = f'<p class="ot-estado-vacio__sugerencia">{sugerencia}</p>' if sugerencia else ""
    # Una sola línea (sin huecos en blanco): ver el comentario equivalente
    # en `encabezado_pagina` — una línea vacía en medio de un bloque HTML
    # de `st.markdown` lo corta y el resto se muestra como texto crudo.
    html = (
        '<div class="ot-estado-vacio">'
        + f'<div class="ot-estado-vacio__motivo">{brand_rings_svg(96)}</div>'
        + f'<div class="ot-estado-vacio__icono">{icono_md(icono, tamano_px=28)}</div>'
        + f'<p class="ot-estado-vacio__mensaje">{mensaje}</p>'
        + sugerencia_html
        + "</div>"
    )
    with card(acento="ninguno"):
        st.markdown(html, unsafe_allow_html=True)


# `empty_state` es el nombre que pide el encargo de rediseño visual (§6
# del informe de A5); `estado_vacio` es el nombre histórico que ya usan
# `views/ajustes.py` y otras vistas — ambos apuntan a la misma función.
empty_state = estado_vacio


def pie_pagina() -> None:
    import streamlit as st

    inyectar_identidad_visual()
    st.markdown('<div class="ot-pie-pagina">Desarrollado por SAVA</div>', unsafe_allow_html=True)


# --------------------------------------------------------- fondo / motivo
def page_background() -> None:
    """El fondo de mármol rosa (base + manchas radiales sutiles, D1) es
    una regla GLOBAL de `assets/theme.css` sobre `html body` — se aplica
    sola en cuanto el CSS está inyectado. Esta función solo existe para
    que una pantalla que no pasa por `encabezado_pagina`/`encabezado_marca`
    (y por lo tanto no inyectaría el CSS todavía) pueda garantizarlo
    explícitamente llamándola una vez al inicio de su `render(ctx)`."""
    inyectar_identidad_visual()


def brand_rings_svg(tamano_px: int = 260) -> str:
    """SVG inline de aros dorados concéntricos (D2): el motivo de marca
    derivado del logo (trazo con degradado bronce -> brillo, sin relleno,
    opacidad 0.35-0.6). Nunca se repite más de una vez por pantalla con
    fuerza — se usa muy tenue detrás del logo (login) o de un icono de
    estado vacío. Devuelve el marcado listo para `st.markdown(...,
    unsafe_allow_html=True)`; no es una imagen, así que escala nítido a
    cualquier tamaño."""
    colores = TOKENS["color"]
    return (
        f'<svg class="ot-aros" width="{tamano_px}" height="{tamano_px}" '
        f'viewBox="0 0 200 200" aria-hidden="true" focusable="false">'
        f"<defs><linearGradient id=\"ot-aro-degradado\" x1=\"0%\" y1=\"0%\" x2=\"100%\" y2=\"100%\">"
        f"<stop offset=\"0%\" stop-color=\"{colores['dorado_bronce']}\"/>"
        f"<stop offset=\"100%\" stop-color=\"{colores['dorado_brillo']}\"/>"
        f"</linearGradient></defs>"
        f'<circle cx="100" cy="100" r="94" fill="none" stroke="url(#ot-aro-degradado)" stroke-width="1.5" opacity="0.4"/>'
        f'<circle cx="100" cy="100" r="86" fill="none" stroke="url(#ot-aro-degradado)" stroke-width="1" opacity="0.55"/>'
        f'<circle cx="100" cy="100" r="78" fill="none" stroke="url(#ot-aro-degradado)" stroke-width="2" opacity="0.3"/>'
        f"</svg>"
    )


def brand_rings(tamano_px: int = 260) -> None:
    """Pinta `brand_rings_svg` dentro de un wrapper posicionado
    (`.ot-aros-wrap`, ver `assets/theme.css`) listo para superponer otro
    elemento encima (logo, icono) con `position: relative` + z-index."""
    import streamlit as st

    st.markdown(f'<div class="ot-aros-wrap">{brand_rings_svg(tamano_px)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ tarjeta
_contador_tarjetas = itertools.count()


@contextmanager
def card(*, acento: str = "superior", key: str | None = None):
    """Tarjeta de marca (D-todas): borde rosa 1px, fondo blanco, radio
    16px, sombra en dos capas, filete dorado de 3px. `acento` en
    {"superior" (por defecto), "izquierdo", "ninguno"}.

    Implementado sobre `st.container(border=True, key=...)`: Streamlit
    añade la clase ESTABLE y DOCUMENTADA `st-key-<key>` al bloque (no es
    una clase autogenerada `.st-emotion-cache-*`, §9) — `assets/theme.css`
    la usa vía `[class*="st-key-ot-card-"]` para pintar el resto del
    look. El `key` se genera automáticamente (único por llamada dentro de
    un mismo rerun) salvo que la vista necesite uno estable propio."""
    import streamlit as st

    inyectar_identidad_visual()
    if key is None:
        key = f"ot-card-{acento}-{next(_contador_tarjetas)}"
    with st.container(border=True, key=key):
        yield


# ---------------------------------------------------------------- KPI card
def kpi_card(etiqueta: str, valor_formateado: str, *, delta: str | None = None, icono: str = "insights") -> None:
    """Tarjeta KPI grande y centrada (D-análisis): icono en círculo
    rosado, cifra 44-52px Inter 700 tabular, etiqueta 13px mayúscula con
    tracking, variación con flecha (sube/baja/neutro) + texto.

    `valor_formateado` ya debe venir de `core.money.format_cop` cuando sea
    dinero (R1) — esta función solo PINTA, nunca calcula. `delta`, si se
    da, también debe venir ya formateado por quien llama (p.ej.
    `core.money.format_percent`); aquí solo se mira el primer caracter
    ('+'/'-') del texto para decidir el icono de flecha, sin recalcular
    ningún número de negocio."""
    import streamlit as st

    delta_html = ""
    if delta:
        texto_delta = str(delta).strip()
        if texto_delta.startswith("-"):
            flecha, clase = "trending_down", "ot-kpi__delta--baja"
        elif texto_delta.startswith("+"):
            flecha, clase = "trending_up", "ot-kpi__delta--sube"
        else:
            flecha, clase = "trending_flat", "ot-kpi__delta--neutro"
        delta_html = (
            f'<div class="ot-kpi__delta {clase}">{icono_md(flecha, tamano_px=16)}{texto_delta}</div>'
        )

    # Una sola línea (sin huecos en blanco) — ver el comentario en
    # `encabezado_pagina` sobre por qué una línea vacía en medio de un
    # bloque HTML de `st.markdown` lo corta a mitad de camino.
    html = (
        '<div class="ot-kpi">'
        + f'<div class="ot-kpi__icono">{icono_md(icono, tamano_px=24)}</div>'
        + f'<div class="ot-kpi__valor">{valor_formateado}</div>'
        + f'<div class="ot-kpi__etiqueta">{etiqueta}</div>'
        + delta_html
        + "</div>"
    )
    with card(acento="superior"):
        st.markdown(html, unsafe_allow_html=True)


def titulo_seccion(texto: str, *, centrado: bool = True) -> None:
    """Subtítulo de sección (H2, D-todas): Playfair Display 600, 30-32px.
    Reemplaza los `st.subheader`/`st.markdown("### ...")` sueltos para que
    toda la app comparta el mismo tratamiento tipográfico de sección."""
    import streamlit as st

    inyectar_identidad_visual()
    clase = "ot-titulo-seccion" + ("" if centrado else " ot-titulo-seccion--izquierda")
    # `<div role="heading">` en vez de un `<h2>` real: Streamlit envuelve
    # cualquier encabezado HTML dentro de `st.markdown` con su propia
    # maquinaria de anclas (id autogenerado + icono de enlace), lo que
    # rompía el centrado/tamaño de este bloque (hallazgo de A5 durante la
    # verificación visual). El rol ARIA conserva la semántica de
    # encabezado para lectores de pantalla sin ese efecto secundario.
    st.markdown(f'<div class="{clase}" role="heading" aria-level="2">{texto}</div>', unsafe_allow_html=True)


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
    (Inter/Playfair Display/Great Vibes/Material Symbols) se autoalojan
    vía `[[theme.fontFaces]]` en `.streamlit/config.toml` — este módulo
    solo aplica el resto del sistema de diseño (tarjetas, KPI, chips,
    foco, reduced-motion, etc.).

    Idempotente DENTRO DE UN MISMO RERUN (ahora casi todos los
    componentes de `core.ui` la llaman al pintar, así que sin esta guarda
    una sola pantalla duplicaría el bloque `<style>` muchas veces): usa
    una bandera en `st.session_state` que `app.py` reinicia al principio
    de cada `main()` con `reiniciar_identidad_visual_para_este_rerun()` —
    por eso la bandera vive en `session_state` (persiste entre reruns)
    pero se borra explícitamente al empezar uno nuevo, nunca se queda en
    `True` para siempre (eso dejaría la segunda pantalla sin estilos)."""
    import streamlit as st

    if st.session_state.get(_IDENTIDAD_VISUAL_INYECTADA_KEY):
        return
    st.session_state[_IDENTIDAD_VISUAL_INYECTADA_KEY] = True
    try:
        css = (_repo_root() / "assets" / "theme.css").read_text(encoding="utf-8")
    except OSError:
        css = ""
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def reiniciar_identidad_visual_para_este_rerun() -> None:
    """Llamada EXCLUSIVA de `app.py` (única propiedad de A5) al principio
    de `main()`, antes de enrutar a cualquier pantalla: borra la bandera
    de `inyectar_identidad_visual()` para que ese rerun vuelva a pintar el
    `<style>` una vez (el DOM anterior ya no existe), sin volver a
    duplicarlo dentro del mismo rerun."""
    import streamlit as st

    st.session_state.pop(_IDENTIDAD_VISUAL_INYECTADA_KEY, None)


def encabezado_marca(
    nombre_negocio: str = "Ola Tata", *, contexto: str = "pantalla", subtitulo: str | None = None
) -> None:
    """Cabecera de marca: logo circular + nombre en Great Vibes, con los
    aros dorados de marca detrás (A3/D1/D2).

    `contexto="pantalla"` (por defecto, usado por login y primer
    arranque): logo grande (220 px) centrado con los aros detrás, nombre
    en script 64px debajo y `subtitulo` opcional (Inter, texto
    secundario) — pensado para la pantalla completa de acceso.
    `contexto="sidebar"`: logo 120px centrado + nombre en script 34px
    debajo, apilados verticalmente (A3: el texto de marca va en texto
    vivo, nunca dentro de la imagen) — pensado para la barra lateral.

    Si el logo aún no se generó (`scripts/build_logo_assets.py` no
    corrió en este entorno) se degrada a solo texto, sin tronar."""
    import streamlit as st

    inyectar_identidad_visual()
    ruta_logo = logo_path("olatata-logo-128.png") if contexto == "sidebar" else logo_path("olatata-logo-256.png")

    if contexto == "sidebar":
        if ruta_logo:
            import base64

            b64 = base64.b64encode(Path(ruta_logo).read_bytes()).decode("ascii")
            st.markdown(
                f"""
                <div class="ot-avatar-sidebar">
                    <div class="ot-aros-wrap ot-aros-wrap--sidebar">{brand_rings_svg(130)}</div>
                    <img src="data:image/png;base64,{b64}" alt="Logo de {nombre_negocio}">
                    <span class="ot-marca-script ot-marca-script--sidebar">{nombre_negocio}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"<div class='ot-marca-script'>{nombre_negocio}</div>", unsafe_allow_html=True)
        return

    subtitulo_html = f'<p class="ot-hero-logo__subtitulo">{subtitulo}</p>' if subtitulo else ""

    # Bloque HTML único (logo + aros + nombre + subtítulo) centrado con
    # flexbox. Antes el logo iba en `st.columns([1, 2, 1])` + `st.image`,
    # que lo alineaba a la IZQUIERDA de la columna central mientras los
    # aros se centraban en otro contenedor: logo corrido y aros
    # desalineados en el login. Una sola línea, sin huecos en blanco (ver
    # el comentario en `encabezado_pagina`).
    logo_html = ""
    if ruta_logo:
        import base64

        b64 = base64.b64encode(Path(ruta_logo).read_bytes()).decode("ascii")
        logo_html = (
            '<div class="ot-hero-marca__logo">'
            + f'<div class="ot-hero-marca__aros">{brand_rings_svg(260)}</div>'
            + f'<img src="data:image/png;base64,{b64}" alt="Logo de {nombre_negocio}" width="200" height="200">'
            + "</div>"
        )
    st.markdown(
        '<div class="ot-hero-marca">'
        + logo_html
        + f"<div class='ot-marca-script ot-marca-script--hero'>{nombre_negocio}</div>"
        + subtitulo_html
        + "</div>",
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


def encabezado_pagina(titulo: str, subtitulo: str | None = None, *, icono: str | None = None) -> None:
    """Encabezado de página — bloque "hero" centrado (C5/D-todas): título
    en Playfair Display 600 (serif clara y legible; la cursiva Great
    Vibes queda reservada SOLO para el nombre de marca "Ola Tata", porque
    en títulos de pantalla costaba leerla),
    subtítulo Inter centrado y filete dorado centrado de 96px debajo.
    `icono`, si se da, pinta un círculo rosado con el icono Material
    encima del título (D-inventario/análisis/ajustes).

    Sin acción principal embebida aquí a propósito: cada vista decide
    dónde poner su botón (p.ej. a la derecha con `st.columns`), este
    helper solo pinta el título/subtítulo/filete de forma consistente."""
    import streamlit as st

    inyectar_identidad_visual()
    subtitulo_html = (
        f"<p class='ot-encabezado-pagina__subtitulo'>{subtitulo}</p>" if subtitulo else ""
    )
    icono_html = (
        f'<div class="ot-encabezado-pagina__icono">{icono_md(icono, tamano_px=28)}</div>' if icono else ""
    )
    # Una sola línea, SIN huecos en blanco entre bloques: una línea vacía
    # en medio de un `<div>` dentro de `st.markdown` cierra el bloque HTML
    # según CommonMark y el resto se muestra como texto crudo en vez de
    # pintarse (hallazgo de A5 durante la verificación visual — pasaba
    # exactamente en esta función cuando `subtitulo=None`, porque esa
    # línea del f-string multilinea quedaba en blanco).
    html = (
        '<div class="ot-encabezado-pagina">'
        + icono_html
        + f'<div class="ot-encabezado-pagina__titulo" role="heading" aria-level="1">{titulo}</div>'
        + subtitulo_html
        + '<div class="ot-encabezado-pagina__filete"></div>'
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# `hero` es el nombre del encargo de rediseño visual; `encabezado_pagina`
# es el nombre histórico que ya usa `views/ajustes.py` — misma función.
hero = encabezado_pagina


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


# `chip` es el nombre del encargo de rediseño visual; `chip_estado` es el
# nombre histórico que ya usan `views/ajustes.py` e `views/inventario.py`.
chip = chip_estado


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


# --------------------------------------------------------- tablas legibles
# Nombres técnicos de columnas (hojas del libro / registros de
# `core.analytics`) -> etiquetas en español para mostrar en pantalla. Las
# tablas son lo que más se mira en Inventario y Análisis: ver
# "stock_actual" o "codigo_barras" se sentía como una hoja de cálculo
# cruda, no como un producto profesional.
ETIQUETAS_COLUMNAS: dict[str, str] = {
    "id": "Código",
    "producto_id": "Producto",
    "nombre": "Nombre",
    "nombre_snapshot": "Producto",
    "categoria": "Categoría",
    "color": "Color",
    "talla_tamano": "Talla / tamaño",
    "proveedor_id": "Proveedor",
    "stock": "Stock",
    "stock_actual": "Stock actual",
    "stock_minimo": "Stock mínimo",
    "stock_en_hoja": "Stock registrado",
    "stock_recalculado": "Stock recalculado",
    "cantidad": "Cantidad",
    "costo": "Costo",
    "precio": "Precio",
    "codigo_barras": "Código de barras",
    "activo": "Activo",
    "sede": "Sede",
    "sede_id": "Sede",
    "numero": "Número",
    "fecha": "Fecha",
    "fecha_local": "Fecha",
    "fecha_hora_utc": "Fecha y hora",
    "hora": "Hora",
    "mes": "Mes",
    "inicio_semana": "Semana desde",
    "canal": "Canal",
    "cliente_nombre": "Cliente",
    "cliente_telefono": "Teléfono",
    "vendedor_nombre": "Vendedor",
    "metodo": "Método de pago",
    "nro_pagos": "N.º de pagos",
    "total": "Total",
    "subtotal": "Subtotal",
    "monto": "Monto",
    "valor": "Valor",
    "ventas_netas": "Ventas netas",
    "ganancia": "Ganancia",
    "costo_vendido": "Costo de lo vendido",
    "margen_pct": "Margen",
    "variacion_pct": "Variación",
    "tickets": "Tickets",
    "ticket_promedio": "Ticket promedio",
    "unidades": "Unidades",
    "unidades_vendidas": "Unidades vendidas",
    "descuento_total": "Descuento",
    "descuentos_otorgados": "Descuentos",
    "envios_cobrados": "Envíos cobrados",
    "devoluciones_unidades": "Unidades devueltas",
    "devoluciones_valor": "Valor devuelto",
    "al_costo": "Valor al costo",
    "al_precio": "Valor al precio",
    "diferencia": "Diferencia",
    "fila": "Fila",
    "columna": "Columna",
    "error": "Error",
    "advertencia": "Advertencia",
    "accion": "Acción",
    "usuario": "Usuario",
    "estado": "Estado",
    "motivo": "Motivo",
    "referencia": "Referencia",
    "notas": "Notas",
    "telefono": "Teléfono",
    "ciudad": "Ciudad",
}

# Columnas que traen pesos enteros (R1): se muestran con `format_cop`.
_COLUMNAS_DINERO = frozenset(
    {
        "costo", "precio", "total", "subtotal", "monto", "valor", "ventas_netas",
        "ganancia", "costo_vendido", "ticket_promedio", "descuento_total",
        "descuentos_otorgados", "envios_cobrados", "devoluciones_valor",
        "al_costo", "al_precio", "precio_unitario", "costo_unitario", "total_linea",
        "reembolso_monto",
    }
)

# Valores internos -> texto legible (métodos de pago y canales).
_VALORES_LEGIBLES: dict[str, dict[str, str]] = {
    "metodo": {
        "efectivo": "Efectivo",
        "datafono": "Datáfono",
        "transferencia": "Transferencia",
        "sistecredito": "Sistecrédito",
        "cambio": "Cambio",
    },
    "canal": {"tienda": "Tienda", "instagram": "Instagram", "whatsapp": "WhatsApp"},
}


def _formatear_dinero_celda(valor: Any) -> Any:
    try:
        import pandas as pd

        if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
            return "—"
    except (TypeError, ValueError):
        pass
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int):
        return format_cop(valor)
    if isinstance(valor, float) and valor.is_integer():
        return format_cop(int(valor))
    return valor  # ya formateado (texto) o no numérico: se deja igual


def _formatear_fecha_utc_celda(valor: Any) -> Any:
    from core.timeutil import parse_iso_utc

    try:
        return formatear_fecha_hora_local(parse_iso_utc(str(valor)))
    except Exception:
        return valor


def tabla_amigable(df: Any) -> Any:
    """Devuelve una COPIA de `df` lista para mostrar: dinero en COP (R1),
    fechas UTC en hora de Bogotá (R2), métodos/canales legibles y
    encabezados en español. Solo presentación: nunca recalcula nada."""
    tabla = df.copy()
    for col in tabla.columns:
        if col in _COLUMNAS_DINERO:
            tabla[col] = tabla[col].map(_formatear_dinero_celda)
        elif col.endswith("_utc"):
            tabla[col] = tabla[col].map(_formatear_fecha_utc_celda)
        elif col in _VALORES_LEGIBLES:
            mapa = _VALORES_LEGIBLES[col]
            tabla[col] = tabla[col].map(lambda v, m=mapa: m.get(str(v), v))
    tabla.columns = [
        ETIQUETAS_COLUMNAS.get(col, str(col).replace("_", " ").strip().capitalize()) for col in tabla.columns
    ]
    return tabla


# ----------------------------------------------------------- impresión
def _html_boton_imprimir(pdf_b64: str, texto: str, nonce: str) -> str:
    """HTML/JS del botón. Abre el PDF (Blob, mismo origen) en un iframe
    oculto y llama a `print()`: sale el diálogo de impresión del sistema
    con el PDF a tamaño real, sin pasar por "Descargas". Si el navegador
    no deja imprimir el iframe, abre el PDF en una pestaña nueva (desde
    ahí: Ctrl+P). Los colores son los del tema (CLAUDE.md §8)."""
    c = TOKENS["color"]
    return f"""
<div style="font-family:Inter,system-ui,sans-serif">
  <button id="b{nonce}" style="width:100%;min-height:46px;border:none;border-radius:16px;
    background:{c['primario']};color:#fff;font-size:16px;font-weight:600;cursor:pointer">
    &#128424;&nbsp; {texto}</button>
  <div id="m{nonce}" style="font-size:13px;color:{c['texto_secundario']};margin-top:4px"></div>
</div>
<script>
(function() {{
  const b64 = "{pdf_b64}";
  const bytes = Uint8Array.from(atob(b64), ch => ch.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {{type: "application/pdf"}}));
  const msg = document.getElementById("m{nonce}");
  document.getElementById("b{nonce}").addEventListener("click", function() {{
    let marco = document.getElementById("f{nonce}");
    if (marco) marco.remove();
    marco = document.createElement("iframe");
    marco.id = "f{nonce}";
    marco.style.cssText = "position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0";
    marco.src = url;
    marco.onload = function() {{
      try {{ marco.contentWindow.focus(); marco.contentWindow.print(); msg.textContent = ""; }}
      catch (e) {{ window.open(url, "_blank"); msg.textContent = "Se abrió el PDF en otra pestaña: imprímelo con Ctrl+P."; }}
    }};
    document.body.appendChild(marco);
  }});
}})();
</script>"""


def boton_imprimir_pdf(pdf_bytes: bytes, texto: str, *, nombre_archivo: str, key: str) -> None:
    """Botón "Imprimir" (diálogo del sistema) + descarga del mismo PDF como
    respaldo. El PDF ya viene al tamaño físico del papel (etiquetas o
    tirilla); en el diálogo hay que elegir la impresora correcta y escala
    "Tamaño real"/100 % (ver docs/IMPRESORAS.md)."""
    import base64

    import streamlit as st
    import streamlit.components.v1 as components

    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    nonce = uuid.uuid4().hex[:8]
    components.html(_html_boton_imprimir(b64, texto, nonce), height=78)
    st.download_button(
        "Descargar PDF",
        data=pdf_bytes,
        file_name=nombre_archivo,
        mime="application/pdf",
        key=key,
        icon=":material/download:",
        use_container_width=True,
    )


def enfocar_campo(etiqueta_aria: str) -> None:
    """Deja el cursor en el campo cuyo `aria-label` coincide, para que el
    lector de códigos USB (que "teclea" el código + Enter) escriba ahí sin
    tener que hacer clic. No roba el foco si el usuario está escribiendo
    en otro campo. El componente vive en un iframe del MISMO origen, por
    eso puede alcanzar `window.parent.document`."""
    import json

    import streamlit.components.v1 as components

    etiqueta = json.dumps(etiqueta_aria)
    components.html(
        f"""<script>
(function() {{
  let intentos = 0;
  function enfocar() {{
    const doc = window.parent.document;
    const campo = doc.querySelector('input[aria-label=' + JSON.stringify({etiqueta}) + ']');
    const activo = doc.activeElement;
    const ocupado = activo && activo !== campo && ["INPUT", "TEXTAREA", "SELECT"].includes(activo.tagName);
    if (campo && !ocupado) {{ campo.focus(); return; }}
    if (!campo && intentos++ < 20) setTimeout(enfocar, 150);
  }}
  setTimeout(enfocar, 120);
}})();
</script><!-- {uuid.uuid4().hex} -->""",
        height=0,
    )


# ---------------------------------------------------------------- guías
def guia(clave: str) -> None:
    """Desplegable "¿Cómo se usa?" con la guía de `core.guias` (pasos
    numerados + nota). Cerrado por defecto para no estorbar al que ya sabe."""
    import html

    import streamlit as st

    from core.guias import obtener_guia

    inyectar_identidad_visual()
    g = obtener_guia(clave)
    pasos = "".join(f"<li>{html.escape(p)}</li>" for p in g.pasos)
    nota = f'<div class="ot-guia__nota">{html.escape(g.nota)}</div>' if g.nota else ""
    with st.container(key=f"ot-guia-{clave}"):
        with st.expander(f"¿Cómo se usa? · {g.titulo}", icon=":material/help:"):
            st.markdown(f'<div class="ot-guia"><ol>{pasos}</ol>{nota}</div>', unsafe_allow_html=True)


_MD_ESPECIALES = "\\`*_{}[]()<>#+-.!|$~"


def md_seguro(texto: object) -> str:
    """Escapa texto libre (nombres de clientes, productos, motivos) antes
    de pasarlo a `st.write`/`st.markdown`: así un nombre como
    `[Paga aquí](http://…)` o `**$ 1.000**` se ve literal y no se convierte
    en un enlace, formato o fórmula LaTeX."""
    return "".join("\\" + c if c in _MD_ESPECIALES else c for c in str(texto))
