# Lista de pruebas en tienda — Ola Tata

Esta lista es para que el dueño o la persona que atiende la tienda prueben
el sistema con casos reales de uso, ANTES de usarlo con ventas de verdad.
No se necesita saber de computadores: solo seguir los pasos y comparar el
resultado con lo que se espera. Si algo no coincide con lo esperado,
anótalo y avisa antes de seguir usando el sistema para vender.

Recomendación: haz estas pruebas con productos y clientes de prueba
(puedes escribir "PRUEBA" en el nombre del cliente), no con ventas reales,
para que no se mezclen con las cuentas del mes.

---

## 1. Venta simple (un solo producto, un solo pago)

**Pasos:**
1. Entra a "Vender".
2. Elige un producto que tenga stock disponible.
3. Vende 1 unidad, cóbrala completa con un solo método de pago (por
   ejemplo efectivo).
4. Confirma la venta.

**Resultado esperado:** la venta aparece de inmediato en "Ventas" con el
total correcto. El stock del producto bajó exactamente en 1 unidad.

---

## 2. Venta dividida (varios productos, pago en dos partes)

**Pasos:**
1. En "Vender", agrega 2 o 3 productos diferentes a la misma venta.
2. Al cobrar, divide el pago en dos métodos distintos (por ejemplo, una
   parte en efectivo y otra en datáfono) de modo que entre los dos sumen
   el total exacto.
3. Confirma la venta.

**Resultado esperado:** la venta se guarda con un solo número de venta,
mostrando los dos pagos por separado, y la suma de los dos pagos es
IGUAL al total de la venta (ni más, ni menos).

---

## 3. Venta con descuento

**Pasos:**
1. Vende un producto y aplica un descuento (en pesos o en porcentaje,
   según lo que ofrezca la pantalla) antes de confirmar.
2. Confirma la venta.

**Resultado esperado:** el total final de la venta es el precio menos el
descuento (más el envío, si lo hubiera). El descuento queda visible por
separado, no se "esconde" dentro del precio.

---

## 4. Devolución (el cliente regresa un producto y le devuelven el dinero)

**Pasos:**
1. Busca una venta ya hecha (puede ser la de la prueba 1).
2. Regístrala como devolución, indicando el motivo.
3. Confirma la devolución.

**Resultado esperado:** el producto devuelto vuelve a aparecer en el
stock disponible (sube la cantidad). Queda un registro de la devolución
con la fecha, el motivo y cuánto dinero se devolvió.

---

## 5. Cambio (el cliente cambia un producto por otro, sin que se mueva
dinero o con una diferencia pequeña)

**Pasos:**
1. Busca una venta ya hecha.
2. Regístrala como "cambio" en vez de devolución normal, y elige el
   producto nuevo que se lleva el cliente.
3. Confirma el cambio.

**Resultado esperado:** el producto que el cliente regresa vuelve al
stock, y el producto nuevo que se lleva sale del stock. Si hay diferencia
de precio, queda registrada claramente (a favor o en contra del
cliente).

---

## 6. Anulación de una venta (se hizo por error y hay que deshacerla
por completo)

**Pasos:**
1. Haz una venta de prueba.
2. Inmediatamente después, anúlala (solo un usuario administrador puede
   hacer esto).
3. Confirma la anulación.

**Resultado esperado:** la venta queda marcada como "anulada" (no se
borra, para que quede el registro). El stock que se había descontado
vuelve a sumarse. La venta anulada ya NO cuenta en los totales del día.

---

## 7. Entrada de mercancía nueva (llegó un pedido del proveedor)

**Pasos:**
1. Entra a "Inventario" y registra una entrada de mercancía: elige el
   producto, la cantidad que llegó y el proveedor.
2. Guarda la entrada.

**Resultado esperado:** el stock del producto sube exactamente en la
cantidad ingresada. Queda un registro de movimiento con la fecha y el
proveedor.

---

## 8. Conteo físico del inventario (contar lo que hay en el local y
ajustar si no coincide con el sistema)

**Pasos:**
1. Cuenta físicamente cuántas unidades hay de un producto en la tienda.
2. En el sistema, compara ese número con lo que dice el stock.
3. Si no coincide, haz el ajuste de conteo indicando la cantidad real.

**Resultado esperado:** el stock del sistema queda igual a lo que
contaste a mano. Queda un registro de "ajuste de conteo" explicando la
diferencia (cuánto decía el sistema antes, cuánto quedó después).

---

## 9. Cuadre de caja al final del día

**Pasos:**
1. Al cerrar el día, entra a "Cuadre de caja".
2. Escribe cuánto efectivo contaste físicamente en la caja.
3. Compara ese número con lo que el sistema calculó que debería haber
   (según las ventas en efectivo del día, más la base inicial).

**Resultado esperado:** el sistema te muestra la diferencia (si la hay)
entre lo que contaste y lo que debería haber, en pesos, sin decimales.
Si todo cuadra, la diferencia es cero.

---

## 10. Cierre de mes de prueba

**Pasos:**
1. Al final del mes (o como prueba, en cualquier momento con datos de
   prueba), un usuario administrador hace el "cierre de mes".
2. Confirma el cierre cuando el sistema lo pida.

**Resultado esperado:** las ventas y movimientos del mes que se cierra
quedan guardados a salvo (archivados) y la pantalla de ventas del mes
queda lista para empezar de nuevo, en cero. El stock de los productos
NO cambia por el cierre (sigue siendo el mismo antes y después). Si algo
falla durante el cierre, el sistema no debe quedar a medias: o se cierra
completo, o no se cierra nada.

---

### Qué hacer si algo no coincide con lo esperado

Anota: qué prueba estabas haciendo, qué esperabas que pasara, y qué pasó
en realidad (una foto de la pantalla ayuda mucho). No sigas usando esa
función con ventas reales hasta que se revise.
