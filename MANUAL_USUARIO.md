# Manual de usuario — Ola Tata · Inventario y Ventas

Guía corta, en español sencillo, de lo que puede hacer cada rol en la
aplicación.

---

## Dueño/a (rol Administrador)

Como dueño/a tienes acceso a **todas** las pantallas: Vender, Ventas,
Inventario, Análisis y Ajustes.

### Vender

1. Entra a **Vender**.
2. Escribe o escanea el nombre, el código o el código de barras del
   producto y presiona Enter (o el botón "Agregar al carrito").
3. Ajusta la cantidad de cada línea del carrito si hace falta, o quítala
   con "Quitar".
4. Si aplica, agrega un descuento (porcentaje o monto fijo), elige el
   canal de venta (Tienda, Instagram o WhatsApp), y si el cliente lo
   pide, el nombre/teléfono y los datos de envío nacional (ciudad,
   transportadora, número de guía).
5. En "Pago" elige el método (efectivo, datáfono, transferencia,
   Sistecrédito o cambio/saldo a favor). Puedes dividir el pago entre
   varios métodos con "+ Agregar método de pago"; el botón "Completar
   con el total restante" llena automáticamente lo que falta.
6. "Confirmar venta" solo se habilita cuando lo pagado coincide
   exactamente con el total.
7. Al confirmar, se muestra el recibo en texto y un botón para enviarlo
   por WhatsApp al cliente. "Nueva venta" limpia el carrito para
   empezar otra.

### Ver y gestionar ventas

En **Ventas** ves **todas** las ventas de todos los vendedores (filtra
por rango de fechas). Cada venta se puede abrir para ver sus productos.

- **Anular una venta**: solo tú puedes hacerlo. Abre la venta → "Anular
  venta" → escribe el motivo (obligatorio) → "Confirmar anulación". El
  stock de los productos se repone automáticamente. No se puede
  deshacer.
- **Devolución o cambio**: elige el producto devuelto, la cantidad, si
  el producto vuelve a stock o se marca como dañado (merma), el método
  de reembolso y el motivo (obligatorio), luego "Registrar devolución".

### Ajustes (solo tú puedes entrar aquí)

En el menú lateral entra a **Ajustes**. Tiene 6 pestañas:

- **Negocio**: nombre del negocio, teléfono de WhatsApp para recibos,
  mensaje del recibo, categorías de producto y métodos de pago activos,
  y los minutos de inactividad antes de cerrar sesión automáticamente.
- **Usuarios**: crea cuentas nuevas (nombre, usuario, rol
  Administrador/Vendedor y una clave temporal generada o propia — la
  persona debe cambiarla al ingresar por primera vez). También puedes
  activar o desactivar usuarios existentes (hay que escribir el nombre
  de usuario para confirmar).
- **Sincronización**: muestra si hay cambios pendientes de subir a
  GitHub o algún conflicto entre lo guardado en este equipo y lo
  remoto.
- **Respaldo**: descarga el archivo `.xlsx` completo de la base de
  datos tal como está en este momento.
- **Integridad**: verifica que el inventario esté consistente.
- **Cierre de mes**: archiva el mes terminado (ventas, pagos,
  devoluciones, movimientos y cuadre de caja) y deja el inventario
  listo para el mes siguiente. Hay que escribir literalmente
  **CERRAR MES** para habilitar el botón. **No se puede deshacer** y
  **nunca** se puede cerrar el mes en curso.

---

## Vendedor/a

Como vendedor/a ves solo **Vender** y **Ventas** (no tienes acceso a
Inventario, Análisis ni Ajustes).

### Vender

Exactamente igual que el proceso del Dueño/a descrito arriba: buscar o
escanear, carrito, descuento, canal, cliente/envío opcional, pago
(puede dividirse en varios métodos) y "Confirmar venta". Al confirmar
obtienes el recibo y el enlace para enviarlo por WhatsApp.

### Ver tus ventas

En **Ventas** solo ves **tus propias** ventas (filtradas por rango de
fechas), no las de otros vendedores ni las del Dueño/a.

- **No puedes anular ventas** — esa opción no aparece en tu pantalla.
- **Sí puedes registrar una devolución o cambio** sobre tus propias
  ventas: mismo formulario que el Dueño/a (producto, cantidad, destino
  del producto, método de reembolso y motivo obligatorio).

### Lo que no puedes hacer

- No ves Inventario ni Análisis.
- No puedes entrar a Ajustes (ni ver usuarios, ni cerrar el mes, ni
  descargar el respaldo). Si lo necesitas, pídeselo al Dueño/a.
