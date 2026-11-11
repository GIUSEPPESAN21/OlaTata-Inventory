"""Zona horaria y cortes de día/semana/mes — SIEMPRE America/Bogota.

CONTRATO CONGELADO — ver docs/CONTRATOS.md. R2 del encargo: todo corte de
día/semana/mes usa `zoneinfo "America/Bogota"`, nunca UTC. Rapi Tienda
(repo de referencia) corta el día con `datetime.now(timezone.utc).date()`
— ese es exactamente el defecto que este módulo existe para evitar.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
UTC = timezone.utc

__all__ = [
    "BOGOTA",
    "UTC",
    "now_utc",
    "to_iso_utc",
    "parse_iso_utc",
    "local_date",
    "month_bounds_utc",
    "week_bounds_utc",
    "start_of_month_local",
]


def now_utc() -> datetime:
    """Momento actual, aware, en UTC."""
    return datetime.now(UTC)


def to_iso_utc(dt: datetime) -> str:
    """Serializa un datetime a ISO-8601 UTC con offset: "2026-11-10T23:30:00+00:00".

    Si `dt` no tiene zona, se asume que YA está en UTC (nunca se asume
    hora local). Si tiene otra zona, se convierte a UTC primero.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def parse_iso_utc(texto: str) -> datetime:
    """Parsea un ISO-8601 (con o sin offset) y devuelve un datetime aware en UTC."""
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_date(dt_utc: datetime) -> date:
    """Convierte un datetime UTC a la fecha calendario en Bogotá (fecha_local).

    Invariante probado: una venta a las 23:30 de Bogotá del 10-nov (que en
    UTC es 04:30 del 11-nov) devuelve `date(2026, 11, 10)`.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    return dt_utc.astimezone(BOGOTA).date()


def _bogota_midnight_to_utc(d: date) -> datetime:
    """00:00:00 de Bogotá de la fecha `d`, convertido a UTC."""
    local_midnight = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=BOGOTA)
    return local_midnight.astimezone(UTC)


def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    """Límites [inicio, fin) del mes calendario de Bogotá, en UTC.

    `inicio` es las 00:00 de Bogotá del día 1 del mes; `fin` es las 00:00
    de Bogotá del día 1 del mes siguiente (límite exclusivo). Útil para
    filtrar `fecha_hora_utc >= inicio and fecha_hora_utc < fin`.
    """
    inicio = _bogota_midnight_to_utc(date(year, month, 1))
    if month == 12:
        siguiente = date(year + 1, 1, 1)
    else:
        siguiente = date(year, month + 1, 1)
    fin = _bogota_midnight_to_utc(siguiente)
    return inicio, fin


def week_bounds_utc(any_local_date: date) -> tuple[datetime, datetime]:
    """Límites [inicio, fin) de la semana (lunes a domingo) de Bogotá, en UTC.

    `inicio` es el lunes 00:00 de Bogotá de la semana que contiene
    `any_local_date`; `fin` es el lunes 00:00 siguiente (límite exclusivo,
    equivalente a "domingo 23:59:59" inclusive).
    """
    lunes = any_local_date - timedelta(days=any_local_date.weekday())
    inicio = _bogota_midnight_to_utc(lunes)
    fin = _bogota_midnight_to_utc(lunes + timedelta(days=7))
    return inicio, fin


def start_of_month_local(d: date) -> date:
    """Día 1 del mes calendario (en fecha local, sin hora) que contiene `d`."""
    return date(d.year, d.month, 1)
