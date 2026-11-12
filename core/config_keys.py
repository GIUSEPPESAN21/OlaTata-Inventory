"""Contrato de claves de la hoja `CONFIG` (ver `docs/CONTRATOS.md`,
sección "Claves de CONFIG"). Única fuente de verdad EJECUTABLE: añadir
una clave nueva aquí Y en `docs/CONTRATOS.md` en el mismo cambio, o
`tests/test_config_keys_contrato.py` falla.

Este módulo no importa Streamlit ni toca `storage` — es solo la lista
de nombres válidos, para que la prueba de contrato pueda escanear el
código fuente sin ejecutar la app.
"""
from __future__ import annotations

# Negocio: editables desde Ajustes -> pestaña "Negocio" (views/ajustes.py).
CLAVES_NEGOCIO = frozenset(
    {
        "negocio_nombre",
        "negocio_whatsapp",
        "negocio_mensaje_recibo",
        "negocio_categorias",
        "negocio_metodos_pago_activos",
    }
)

# Operación / sesión.
CLAVES_OPERACION = frozenset(
    {
        "sesion_minutos",
        "permitir_vender_sin_stock",
        "ultimo_mes_cerrado",
        # Usada por views/vender.py para el enlace de WhatsApp del recibo.
        # Nota: es una clave DISTINTA de `negocio_whatsapp` (ver hallazgo
        # en docs/CONTRATOS.md) — documentada así porque es lo que el
        # código hace hoy, no lo que "debería" hacer.
        "telefono_whatsapp",
        # Registro informativo de progreso del cierre de mes (JSON), para
        # que un admin vea en qué quedó un cierre interrumpido. NUNCA se
        # usa para decidir por dónde reanudar (ver core/monthly_close.py).
        "cierre::progreso",
    }
)

# Informativas: sembradas por scripts/seed_db.py; ningún módulo las lee
# todavía (reservadas para un futuro encabezado/tema).
CLAVES_INFORMATIVAS = frozenset(
    {
        "instagram",
        "ciudades",
        "zona_horaria",
        "moneda",
    }
)

CLAVES_CONOCIDAS = CLAVES_NEGOCIO | CLAVES_OPERACION | CLAVES_INFORMATIVAS

# Prefijo de las claves internas de contadores (`Storage.next_counter`):
# `contador::<nombre>::<reset_key o 'global'>`. Nunca se leen/escriben
# por nombre literal fuera de `next_counter` mismo, así que no se
# enumeran una a una en `CLAVES_CONOCIDAS`.
PREFIJO_CONTADOR = "contador::"


def es_clave_conocida(clave: str) -> bool:
    return clave in CLAVES_CONOCIDAS or clave.startswith(PREFIJO_CONTADOR)
