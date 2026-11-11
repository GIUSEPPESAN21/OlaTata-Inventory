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
from typing import Any

from core.money import format_cop
from core.timeutil import BOGOTA, UTC

logger = logging.getLogger("olatata.ui")

__all__ = [
    "PASSWORD_MIN_LENGTH",
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
]

PASSWORD_MIN_LENGTH = 8
_ALFABETO_PASSWORD_TEMPORAL = string.ascii_letters + string.digits


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


def inyectar_identidad_visual() -> None:
    """Carga Inter/Dancing Script desde Google Fonts y los aplica con
    selectores ESTABLES (`html`, `body`, `data-testid`) — nunca clases
    autogeneradas `.st-emotion-cache-*` (§9: esa es la falla real que se
    encontró en el repo de referencia Rapi Tienda)."""
    import streamlit as st

    st.markdown(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Dancing+Script:wght@600&display=swap" rel="stylesheet">
        <style>
        html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
            font-family: 'Inter', sans-serif;
        }
        .ola-tata-marca {
            font-family: 'Dancing Script', cursive;
            font-size: 2.1rem;
            color: #C2185B;
            line-height: 1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def encabezado_marca(nombre_negocio: str = "Ola Tata") -> None:
    """Cabecera con el nombre del negocio en Dancing Script (§9: sin logo
    por ahora, así que se usa tipografía de marca en vez de una imagen)."""
    import streamlit as st

    inyectar_identidad_visual()
    st.markdown(f"<div class='ola-tata-marca'>{nombre_negocio}</div>", unsafe_allow_html=True)
