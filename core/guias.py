"""Guías de uso ("¿Cómo se usa?") de cada pantalla y pestaña.

Todas en un solo lugar para que tengan el mismo tono y formato, y para
poder revisarlas o corregirlas sin buscar por las vistas. Cada guía es un
título corto, pasos numerados y, si hace falta, una nota de cuidado.
`core.ui.guia(clave)` las pinta como un desplegable discreto (cerrado por
defecto) debajo del título. Sin Streamlit: es solo texto.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Guia", "GUIAS", "obtener_guia"]


@dataclass(frozen=True)
class Guia:
    titulo: str
    pasos: tuple[str, ...]
    nota: str | None = None


GUIAS: dict[str, Guia] = {
    # ------------------------------------------------------------- Vender
    "vender": Guia(
        "Cómo registrar una venta",
        (
            "Escanea la etiqueta con el lector: el cursor ya está en el buscador, no hace falta hacer clic. "
            "También puedes escribir el nombre exacto o el código y oprimir Enter.",
            "Si escaneas el mismo producto otra vez, la cantidad sube sola. Puedes cambiarla o quitar la línea.",
            "Elige el descuento (porcentaje o monto), el canal (Tienda, Instagram, WhatsApp) y, si aplica, "
            "los datos del cliente y del envío.",
            "En Pago elige el método. Para pagar con dos métodos usa «Agregar método de pago»; "
            "«Completar con el total restante» llena el último monto.",
            "Oprime «Cobrar». Luego puedes imprimir el recibo en la tirilla o enviarlo por WhatsApp.",
        ),
        "El botón «Cobrar» solo se activa cuando lo pagado es exactamente igual al total.",
    ),
    # ------------------------------------------------------------- Ventas
    "ventas": Guia(
        "Cómo consultar, devolver o anular",
        (
            "Elige el rango de fechas con «Desde» y «Hasta» (por defecto, la última semana).",
            "Abre una venta para ver el detalle: productos, vendedor, canal y cliente.",
            "«Devolución / cambio»: elige el producto, la cantidad, si vuelve al stock o se da de baja, "
            "cómo se reembolsa y escribe el motivo.",
            "«Anular venta» (administrador o maestro): deshace la venta completa y devuelve el stock. "
            "El motivo es obligatorio y queda registrado.",
            "«Editar datos» (solo maestro): corrige cliente, teléfono, canal, envío o nota. "
            "Los productos y montos no se editan: para eso se anula o se hace una devolución.",
        ),
        "Cada vendedor ve solo sus propias ventas; el administrador ve todas.",
    ),
    # ---------------------------------------------------------- Inventario
    "inventario": Guia(
        "Cómo está organizado el inventario",
        (
            "«Productos»: busca, filtra, crea y edita productos.",
            "«Entrada de mercancía»: suma unidades cuando llega mercancía nueva.",
            "«Conteo físico»: corrige el stock cuando lo que cuentas no coincide con el sistema.",
            "«Importar inventario»: carga muchos productos de una vez desde Excel o CSV.",
            "«Etiquetas»: imprime etiquetas de precio con código de barras.",
            "«Integridad»: comprueba que el stock cuadre con el historial de movimientos.",
        ),
        "El stock nunca se escribe a mano: siempre cambia por una venta, una entrada, un conteo o una devolución, "
        "y cada cambio queda en el historial.",
    ),
    "inventario_productos": Guia(
        "Productos",
        (
            "Usa el buscador, la categoría o las casillas «Bajo mínimo» / «Sin stock» para filtrar la tabla.",
            "Para crear uno abre «Nuevo producto»: nombre, categoría, costo, precio, stock mínimo y stock inicial. "
            "El código de barras es opcional (si no tiene, la etiqueta usa uno interno).",
            "Para corregir datos elige el producto en «Editar / activar / desactivar» y guarda los cambios.",
            "Desactiva los productos que ya no vendes en lugar de borrarlos: así se conserva su historial.",
        ),
    ),
    "inventario_entrada": Guia(
        "Entrada de mercancía",
        (
            "Elige el producto que llegó.",
            "Escribe cuántas unidades entran y el costo unitario de esta compra.",
            "Opcional: el proveedor y el número de factura o remisión.",
            "Oprime «Registrar entrada». El stock sube y el costo promedio se recalcula solo.",
        ),
        "Después de registrar la entrada, imprime las etiquetas de esas unidades en la pestaña «Etiquetas».",
    ),
    "inventario_conteo": Guia(
        "Conteo físico",
        (
            "Cuenta las unidades reales del producto en la tienda.",
            "Elige el producto y escribe la cantidad contada.",
            "Si no coincide con el sistema, escribe el motivo (pérdida, daño, error de conteo…) y registra el conteo.",
        ),
        "El ajuste queda guardado con fecha, usuario y motivo.",
    ),
    "inventario_importar": Guia(
        "Importar inventario",
        (
            "Descarga la plantilla y llénala en Excel, una fila por producto.",
            "Sube el archivo (.xlsx o .csv). La app revisa cada fila y te muestra los errores antes de guardar.",
            "Revisa la vista previa, marca la casilla de confirmación y oprime «Importar inventario inicial».",
        ),
        "Si hay errores no se importa nada: corrige el archivo y súbelo de nuevo.",
    ),
    "inventario_etiquetas": Guia(
        "Etiquetas de precio",
        (
            "Revisa que el tamaño del rollo coincida con el de la impresora (por defecto, 3 por fila de 32 × 25 mm). "
            "Si cambias medidas, oprime «Guardar como predeterminado».",
            "La primera vez imprime la «Hoja de prueba»: los recuadros deben caer dentro de las etiquetas.",
            "Marca «Imprimir» en cada producto y ajusta la cantidad de etiquetas (por defecto, una por unidad en stock).",
            "Revisa la vista previa y oprime «Imprimir etiquetas». En el diálogo elige la impresora de etiquetas "
            "y escala 100 % (tamaño real).",
        ),
        "Escanea una etiqueta impresa antes de pegar el lote completo. Guía completa en docs/IMPRESORAS.md.",
    ),
    "inventario_integridad": Guia(
        "Integridad",
        (
            "Oprime «Verificar integridad ahora».",
            "La app recalcula el stock de cada producto desde su historial y lo compara con el registrado.",
            "Si aparece alguna diferencia, revisa ese producto y haz un conteo físico.",
        ),
    ),
    # ----------------------------------------------------------- Análisis
    "analisis": Guia(
        "Cómo leer el análisis",
        (
            "«Hoy»: ventas, tickets, unidades, ticket promedio, ganancia y margen del día, más el cuadre de caja.",
            "«Semana» y «Mes»: ventas por día y productos más vendidos, comparados con el período anterior.",
            "«Meses anteriores»: el resumen de los meses ya cerrados.",
            "Usa «Exportar a Excel» para llevarte el reporte del período.",
        ),
        "El vendedor ve solo sus ventas, sin costos ni ganancia. Las fechas siempre están en hora de Colombia.",
    ),
    # ------------------------------------------------------------- Ajustes
    "ajustes": Guia(
        "Qué se configura aquí",
        (
            "«Negocio»: nombre, WhatsApp, mensaje del recibo, categorías, métodos de pago y tiempo de sesión.",
            "«Usuarios»: crea vendedores, restablece claves y desactiva cuentas.",
            "«Sincronización»: estado de la base de datos en la nube (GitHub).",
            "«Respaldo»: descarga una copia completa de la base.",
            "«Integridad» y «Cierre de mes»: controles del final de mes.",
        ),
        "Solo el administrador puede entrar a Ajustes.",
    ),
    "ajustes_negocio": Guia(
        "Datos del negocio",
        (
            "Edita los campos y oprime «Guardar».",
            "Las categorías y los métodos de pago aparecen después en Inventario y en Vender.",
            "«Minutos de sesión»: tiempo sin uso tras el cual la app pide ingresar de nuevo.",
        ),
    ),
    "ajustes_usuarios": Guia(
        "Usuarios",
        (
            "Crea una cuenta por persona; nunca compartan usuario.",
            "Al crearla, entrega la clave temporal en persona: el sistema le pedirá cambiarla al primer ingreso.",
            "Si alguien deja de trabajar en el negocio, desactiva su cuenta: sale de inmediato y conserva su historial.",
            "«Restablecer clave» genera una nueva clave temporal y cierra todas sus sesiones abiertas.",
            "«Editar» (solo maestro): cambia nombre, usuario o rol. Si cambia el usuario o el rol, "
            "esa persona debe volver a ingresar.",
        ),
        "Las claves deben tener al menos 10 caracteres, con letras y números.",
    ),
    "ajustes_sincronizacion": Guia(
        "Sincronización con la nube",
        (
            "En verde: la base está guardada en GitHub y al día.",
            "«Cambios por sincronizar»: no hubo internet; la venta está a salvo y se sube con «Sincronizar ahora» "
            "o en la próxima operación.",
            "«Conflicto»: la base en GitHub cambió por fuera de la app. Elige qué versión conservar y escribe "
            "CONFIRMAR. Ninguna opción borra datos.",
        ),
    ),
    "ajustes_datos_prueba": Guia(
        "Datos de prueba (solo maestro)",
        (
            "«Crear datos de prueba» agrega prueba.admin, prueba.vendedor, un producto «[PRUEBA] Bolso de prueba» "
            "y una venta simulada de 2 unidades.",
            "Anota las dos claves que aparecen: se muestran una sola vez.",
            "Cierra sesión y entra con cada usuario de prueba para ver qué puede hacer cada rol.",
            "Al terminar, escribe ELIMINAR y oprime «Eliminar datos de prueba»: se borra todo lo de prueba "
            "y la base queda solo con los datos reales.",
        ),
        "Mientras existan, la venta de prueba suma en Análisis. Elimínalos antes de empezar a vender de verdad.",
    ),
    "ajustes_respaldo": Guia(
        "Respaldo",
        (
            "Descarga la copia completa de la base (Excel) y guárdala en un lugar seguro.",
            "Recomendado: una vez por semana y siempre antes del cierre de mes.",
        ),
        "El archivo contiene datos de clientes y ventas: no lo compartas ni lo envíes por chat.",
    ),
    "ajustes_integridad": Guia(
        "Integridad",
        (
            "Comprueba que el stock de cada producto coincida con su historial de movimientos.",
            "Hazlo antes del cierre de mes.",
        ),
    ),
    "ajustes_cierre": Guia(
        "Cierre de mes",
        (
            "Se hace al terminar el mes, cuando ya no habrá más ventas de ese mes.",
            "Descarga un respaldo antes.",
            "Escribe CERRAR MES y confirma. Las ventas del mes se archivan y la app queda lista para el mes nuevo.",
        ),
        "El stock NO se reinicia. El cierre verifica el archivo antes de limpiar nada; si algo falla, no toca los datos.",
    ),
}


def obtener_guia(clave: str) -> Guia:
    try:
        return GUIAS[clave]
    except KeyError as exc:
        raise KeyError(f"No hay guía de uso para '{clave}'.") from exc
