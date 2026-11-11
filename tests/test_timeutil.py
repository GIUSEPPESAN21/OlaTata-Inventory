from datetime import date, datetime, timezone

from core.timeutil import (
    BOGOTA,
    local_date,
    month_bounds_utc,
    parse_iso_utc,
    to_iso_utc,
    week_bounds_utc,
)


def test_venta_23_30_bogota_cuenta_el_dia_correcto_aunque_utc_sea_otro_dia():
    # 23:30 Bogotá del 10-nov == 04:30 UTC del 11-nov (Bogotá es UTC-5, sin DST).
    dt_utc = datetime(2026, 11, 11, 4, 30, 0, tzinfo=timezone.utc)
    assert local_date(dt_utc) == date(2026, 11, 10)


def test_local_date_con_datetime_naive_se_asume_utc():
    dt_naive = datetime(2026, 11, 11, 4, 30, 0)
    assert local_date(dt_naive) == date(2026, 11, 10)


def test_to_iso_utc_y_parse_iso_utc_roundtrip():
    dt = datetime(2026, 11, 10, 23, 30, 0, tzinfo=BOGOTA)
    iso = to_iso_utc(dt)
    assert iso == "2026-11-11T04:30:00+00:00"
    de_vuelta = parse_iso_utc(iso)
    assert de_vuelta == dt.astimezone(timezone.utc)


def test_month_bounds_utc_nov_2026():
    inicio, fin = month_bounds_utc(2026, 11)
    # 1 de noviembre 00:00 Bogotá = 1 de noviembre 05:00 UTC
    assert inicio == datetime(2026, 11, 1, 5, 0, 0, tzinfo=timezone.utc)
    # 1 de diciembre 00:00 Bogotá = 1 de diciembre 05:00 UTC
    assert fin == datetime(2026, 12, 1, 5, 0, 0, tzinfo=timezone.utc)


def test_month_bounds_utc_diciembre_cruza_anio():
    inicio, fin = month_bounds_utc(2026, 12)
    assert inicio == datetime(2026, 12, 1, 5, 0, 0, tzinfo=timezone.utc)
    assert fin == datetime(2027, 1, 1, 5, 0, 0, tzinfo=timezone.utc)


def test_month_bounds_incluye_venta_23_30_del_dia_1_pero_no_la_de_antes():
    inicio, fin = month_bounds_utc(2026, 11)
    # Venta el 31-oct a las 23:30 Bogotá -> NO debe estar en noviembre.
    venta_oct_31 = datetime(2026, 11, 1, 4, 30, 0, tzinfo=timezone.utc)
    assert not (inicio <= venta_oct_31 < fin)
    # Venta el 1-nov a las 00:01 Bogotá -> SI debe estar en noviembre.
    venta_nov_1 = datetime(2026, 11, 1, 5, 1, 0, tzinfo=timezone.utc)
    assert inicio <= venta_nov_1 < fin


def test_week_bounds_utc_lunes_a_domingo():
    # 11-nov-2026 es miércoles. La semana debe iniciar el lunes 9-nov.
    inicio, fin = week_bounds_utc(date(2026, 11, 11))
    assert inicio == datetime(2026, 11, 9, 5, 0, 0, tzinfo=timezone.utc)
    assert fin == datetime(2026, 11, 16, 5, 0, 0, tzinfo=timezone.utc)


def test_week_bounds_utc_cruza_mes():
    # 1-dic-2026 es martes; la semana inicia el lunes 30-nov.
    inicio, fin = week_bounds_utc(date(2026, 12, 1))
    assert inicio == datetime(2026, 11, 30, 5, 0, 0, tzinfo=timezone.utc)
    assert fin == datetime(2026, 12, 7, 5, 0, 0, tzinfo=timezone.utc)


def test_domingo_23_59_59_bogota_esta_dentro_de_la_semana():
    inicio, fin = week_bounds_utc(date(2026, 11, 11))
    domingo_tarde = datetime(2026, 11, 15, 23, 59, 59, tzinfo=BOGOTA).astimezone(timezone.utc)
    assert inicio <= domingo_tarde < fin
    lunes_siguiente_00_00 = datetime(2026, 11, 16, 0, 0, 0, tzinfo=BOGOTA).astimezone(timezone.utc)
    assert not (inicio <= lunes_siguiente_00_00 < fin)
