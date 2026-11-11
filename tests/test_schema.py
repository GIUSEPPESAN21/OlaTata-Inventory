from core import schema


def test_todas_las_hojas_tienen_columnas_definidas():
    for name in schema.SHEET_NAMES:
        assert name in schema.SHEET_COLUMNS
        assert len(schema.columnas(name)) > 0


def test_todas_las_hojas_excepto_config_tienen_id():
    for name in schema.SHEET_NAMES:
        if name == schema.CONFIG:
            continue
        if name == schema.STOCK:
            # stock usa clave compuesta (producto_id, sede_id), no "id" propio.
            assert "producto_id" in schema.columnas(name)
            continue
        assert "id" in schema.columnas(name), f"{name} no tiene columna 'id'"


def test_todas_las_hojas_tienen_created_y_updated_at():
    for name in schema.SHEET_NAMES:
        cols = schema.columnas(name)
        assert "created_at" in cols
        assert "updated_at" in cols


def test_columnas_devuelve_copia_independiente():
    a = schema.columnas(schema.PRODUCTOS)
    a.append("hackeada")
    b = schema.columnas(schema.PRODUCTOS)
    assert "hackeada" not in b
