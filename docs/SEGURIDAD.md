# Seguridad — Ola Tata · Inventario y Ventas

Qué protege la app, cómo, y qué le toca hacer al dueño. Revisión del
2026-11-13.

## Controles en la aplicación

| Riesgo | Control | Dónde |
|---|---|---|
| Adivinar claves (fuerza bruta) | bcrypt; bloqueo de 15 min tras 5 fallos por usuario; **pausa creciente** (1, 2, 4, 8 s) por sesión del navegador; mensaje genérico que no revela si el usuario existe; tiempo de respuesta igualado | `core/auth.py`, `core/seguridad.py`, `views/login.py` |
| Claves débiles | Mínimo **10** caracteres, letras y números, no comunes, sin el usuario ni el nombre. Claves temporales aleatorias (`secrets`) que siempre cumplen | `core/seguridad.py` |
| Sesión robada u olvidada abierta | Expira por inactividad (configurable) y a las **12 h** aunque haya actividad; se revoca al cambiar o restablecer la clave y al desactivar la cuenta | `app.py`, `core/auth.py` |
| Clave olvidada / empleado que se va | **Restablecer clave** (admin): temporal nueva, cambio obligatorio, cierra todas sus sesiones. Desactivar cuenta: efecto inmediato | Ajustes → Usuarios |
| Quedarse fuera del sistema | No se puede desactivar la propia cuenta ni al último administrador activo | `core/seguridad.py` |
| Acciones sin permiso | Permisos revalidados en `core/` en cada acción (ocultar un botón no basta) | `core/permissions.py` |
| No saber quién hizo qué | **Registro de seguridad**: ingresos, cambios/restablecimientos de clave, usuarios creados/activados/desactivados, cierres de mes (nunca guarda contraseñas) | Ajustes → Usuarios |
| Fugas por mensajes de error | `showErrorDetails = "none"`: el navegador nunca ve trazas; el usuario ve un código de incidente y el detalle va al log del servidor | `.streamlit/config.toml` |
| Inyección en textos (Markdown/HTML/LaTeX) | Nombres, clientes y motivos se escapan antes de mostrarse; HTML propio con `html.escape` | `core.ui.md_seguro` |
| Fórmulas en Excel | Todo texto se guarda como texto (`inlineStr`): un "=..." nunca se ejecuta | `core/excel_safe.py`, `core/fastxlsx.py` |
| Nombres de usuario engañosos | Solo `a-z 0-9 . _ -` (sin espacios, tildes ni letras de otros alfabetos) | `core/seguridad.py` |
| Pérdida o sobrescritura de datos | La base se descarga de GitHub antes de escribir; nunca publica a ciegas; conflictos detectados por SHA | `core/storage.py` |
| Librerías con fallas conocidas | Versiones fijadas; **Pillow 11.3 → 13.0** (76 vulnerabilidades conocidas corregidas); `pip-audit` en cada CI | `requirements.txt`, CI |
| Opciones de desarrollador visibles | Barra superior de Streamlit oculta, `toolbarMode = "minimal"` | `assets/theme.css`, config |
| Peticiones cruzadas (CSRF) | `enableXsrfProtection = true` | config |

## Lista de chequeo del dueño (lo que la app no puede hacer sola)

1. **GitHub con verificación en dos pasos (2FA)** en la cuenta `GIUSEPPESAN21`:
   quien entra a esa cuenta tiene toda la base de datos.
2. **Token fine-grained** limitado a `OlaTata-Database` y `OlaTata-Archive`,
   solo `Contents: Read and write`, con **vencimiento** (ver `DEPLOY.md`).
   Si se filtra: revócalo en GitHub y crea otro en los Secrets de Streamlit.
3. `OlaTata-Database` y `OlaTata-Archive` deben seguir **privados**
   (verificado el 2026-11-13). `OlaTata-Inventory` puede ser público: no
   tiene datos ni secretos.
4. Opcional, capa extra: en Streamlit Cloud → app → **Settings → Sharing**,
   limitar quién puede abrir la app a correos invitados.
5. Clave del administrador única (no reutilizada en otros sitios) y un
   usuario por persona: nunca compartir cuentas.
6. Revisar Ajustes → Usuarios → **Registro de seguridad** de vez en cuando
   (ingresos a horas raras, restablecimientos no hechos por ti).
7. Descargar un **respaldo** semanal y guardarlo fuera del computador de la tienda.

## Límites conocidos (honestos)

- Los bloqueos por intentos viven en la memoria del servidor: un reinicio
  de Streamlit Cloud los borra (la pausa por sesión y bcrypt siguen
  frenando el ataque).
- Streamlit Cloud no permite poner cabeceras HTTP propias (CSP,
  X-Frame-Options); las gestiona la plataforma.
- El botón "Manage app" (abajo a la derecha) lo pone Streamlit Cloud fuera
  de la app; solo lo ve el dueño de la cuenta y no se puede quitar desde el código.
