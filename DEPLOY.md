# Despliegue — Ola Tata · Inventario y Ventas

## 1. Crear el token (fine-grained PAT)

La app necesita un token de GitHub para leer y escribir en `OlaTata-Database`
y publicar cierres en `OlaTata-Archive`. **Nunca** se usa un token clásico con
acceso a toda la cuenta.

1. Entra a GitHub → tu foto de perfil → **Settings** → **Developer settings**
   → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. **Resource owner**: `GIUSEPPESAN21`.
3. **Expiration**: la que prefieras (recomendado: 1 año, con recordatorio para
   renovarlo).
4. **Repository access** → **Only select repositories** → marca únicamente:
   - `OlaTata-Database`
   - `OlaTata-Archive`
5. **Permissions** → **Repository permissions** → **Contents**: `Read and write`.
   Todo lo demás debe quedar en `No access`. No se necesita acceso a Issues,
   Actions, Metadata extra, Pull requests, etc.
6. Genera el token y cópialo una sola vez (GitHub no lo vuelve a mostrar).

## 2. Configurar los secretos

Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` (este
archivo está en `.gitignore`, nunca se sube) y completa:

```toml
GITHUB_TOKEN = "github_pat_xxx..."
GITHUB_REPO = "GIUSEPPESAN21/OlaTata-Database"
GITHUB_REPO_ARCHIVE = "GIUSEPPESAN21/OlaTata-Archive"
```

En Streamlit Community Cloud, estos mismos valores se pegan en
**App settings → Secrets**, no en un archivo del repo.

## 3. Despliegue en Streamlit Community Cloud

1. Entra a [share.streamlit.io](https://share.streamlit.io) con la cuenta
   de GitHub `GIUSEPPESAN21` (la misma que es "Resource owner" del PAT
   del paso 1).
2. **Create app** → **Deploy a public app from GitHub** (o el botón
   equivalente de "New app" según la versión actual de la consola).
3. **Repository**: `GIUSEPPESAN21/OlaTata-Inventory` (este repositorio,
   el que tiene el código — no `OlaTata-Database` ni `OlaTata-Archive`,
   que son solo datos).
4. **Branch**: `main`.
5. **Main file path**: `app.py`.
6. Antes de desplegar (o justo después, desde **Manage app** →
   **⋮** → **Settings**), abre **App settings → Secrets** y pega los 3
   valores en formato TOML (los mismos del paso 2, sin comillas de
   markdown):

   ```toml
   GITHUB_TOKEN = "github_pat_xxx..."
   GITHUB_REPO = "GIUSEPPESAN21/OlaTata-Database"
   GITHUB_REPO_ARCHIVE = "GIUSEPPESAN21/OlaTata-Archive"
   ```

7. Guarda los secretos y despliega (o reinicia la app si ya estaba
   corriendo — Streamlit Cloud reinicia solo al guardar secretos nuevos).

### Nota sobre repositorio privado vs. público (a verificar al desplegar)

Streamlit Community Cloud (el plan gratuito) **puede** desplegar desde
repositorios privados de GitHub siempre que la cuenta de Streamlit esté
conectada vía OAuth a esa cuenta/organización de GitHub y la app
autorice el acceso a repos privados durante la conexión inicial. Sin
embargo, esto depende de la cuenta concreta (`GIUSEPPESAN21`) y de los
permisos que el conector de GitHub tenga otorgados en ese momento — no
hay garantía documentada aquí de que funcione sin fricción la primera
vez. **A verificar al desplegar realmente:**

- Si `OlaTata-Inventory` (este repo de código) se mantiene privado, hay
  que confirmar en la consola de Streamlit Cloud que aparece en la lista
  de repos disponibles al crear la app (si no aparece, normalmente hace
  falta reautorizar la "Streamlit" GitHub App en
  github.com/settings/installations para darle acceso a ese repo
  específico).
- Si Streamlit Cloud no permite desplegar desde el repo privado con la
  cuenta actual, la alternativa es hacer público `OlaTata-Inventory`
  (el código en sí no contiene datos de clientes ni secretos — esos
  viven en `OlaTata-Database`/`OlaTata-Archive`, que SÍ deben seguir
  privados, y en los Secrets de la app, que nunca se suben al repo).
- Esta nota describe el comportamiento esperado de la plataforma, no un
  resultado confirmado en este proyecto: no se ha hecho todavía un
  despliegue real para confirmarlo.

### Verificar que la base de datos en la nube quedó conectada

1. Entra con el usuario administrador.
2. En la barra lateral, debajo del menú, debe verse el indicador
   **"Base en la nube al día"** (icono de nube). Si dice **"Modo local
   (sin nube)"**, la app no encontró `GITHUB_TOKEN` en los Secrets.
3. En **Ajustes → Sincronización** debe aparecer "Conectado a GitHub ·
   GIUSEPPESAN21/OlaTata-Database" y la versión (sha) cargada.
4. Haz un cambio pequeño (p.ej. guarda la pestaña Negocio) y revisa que
   aparezca un commit nuevo "Actualiza OLATATA_DB.xlsx (...)" en el repo
   `OlaTata-Database`.

Al arrancar, la app **descarga** `OLATATA_DB.xlsx` de GitHub antes de
mostrar nada (la nube es la fuente de verdad; el disco de Streamlit
Cloud se borra en cada reinicio). Si GitHub no responde, verás "Sin
conexión con la base de datos" con un botón **Reintentar** — la app
nunca arranca con una base vacía, para no sobrescribir los datos reales.
Si alguna clave de configuración del negocio falta (categorías, métodos
de pago, WhatsApp…), la app la restaura sola con su valor por defecto,
sin tocar las que ya editaste.

## 4. Primer arranque en Windows (PowerShell)

```powershell
# 1. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Instalar dependencias (incluye las de desarrollo/pruebas)
pip install -r requirements-dev.txt

# 3. Correr la app
streamlit run app.py
```

Al abrir la app por primera vez, `app.py` revisa si la hoja `usuarios`
del libro (`OLATATA_DB.xlsx`, o el que apunte `OLATATA_DB_PATH`) está
vacía. Si lo está, en vez de pedir login aparece el asistente de
**primer arranque** (`views/primer_arranque.py`): crea el usuario
administrador con una contraseña temporal y, en el primer login,
obliga a cambiarla antes de continuar (`must_change_password=True`,
ver `core/auth.py`).

Sin `.streamlit/secrets.toml`, todo esto funciona igual en modo 100%
local: `core.config.safe_secret` nunca truena si no hay secretos, y
`Storage` arranca con `sync_enabled=False` — el libro se guarda solo en
disco (`OLATATA_DB.xlsx` en la raíz del repo), sin publicar a GitHub.
Para probar la sincronización real, completa los secretos del paso 2.

## 5. Restaurar una versión anterior de `OLATATA_DB.xlsx`

Cada `transaction()` que termina sin excepción publica el `.xlsx`
completo a `OlaTata-Database` con un `PUT` a la API de contenidos de
GitHub (`core/storage.py:_github_put`), lo que GitHub registra como un
commit real. En la práctica, el `git log` de `OlaTata-Database` **es**
el historial de versiones del libro vivo: un commit por cada venta,
cierre de caja, cambio de ajustes, etc. que se guardó con éxito.

**Antes de restaurar nada**, dos cosas del contrato de `core/storage.py`
que importan para no romper la sincronización después:

- El `PUT` siempre manda como `sha` el que GitHub reporta en ese
  instante para el archivo (`_github_get_sha`), nunca un valor
  inventado — así que cualquier commit manual que hagas (vía la web de
  GitHub o la API) es válido mientras uses el SHA real del commit
  anterior, igual que haría la app.
- La instancia de `Storage` que ya está corriendo (el proceso de
  Streamlit) guarda en memoria el SHA remoto de la **última
  publicación que ella misma hizo** (`_known_remote_sha`). Si restauras
  una versión anterior por fuera de la app mientras ese proceso sigue
  vivo, la siguiente venta/ajuste que intente publicar va a notar que
  el SHA remoto real ya no coincide con el que la app recordaba y
  lanzará `ConflictoDeSincronizacionError` (marca
  `sync_status().en_conflicto = True`, visible en Ajustes →
  Sincronización) — **aunque la restauración en sí haya sido exitosa**.
  Para evitar ese falso conflicto, **reinicia la app** (`streamlit run
  app.py` de nuevo) justo después de restaurar manualmente: un proceso
  nuevo arranca con `_known_remote_sha = None` y en su primer `PUT`
  simplemente usa el SHA real vigente, sin comparar contra nada viejo.

  Si de todas formas aparece el conflicto, resuélvelo desde la app:
  **Ajustes → Sincronización → "Usar la versión de la nube (GitHub)"**
  (recarga la versión restaurada; la copia del servidor se guarda como
  respaldo) y escribe `CONFIRMAR`. Ya no hace falta intervenir por fuera.

### Opción A — ver y extraer una versión anterior con `git`

```bash
git clone https://github.com/GIUSEPPESAN21/OlaTata-Database.git
cd OlaTata-Database
git log --oneline -- OLATATA_DB.xlsx   # un commit por publicación

# Extrae el contenido de un commit puntual a un archivo aparte,
# SIN tocar el historial ni el archivo actual en GitHub:
git show <hash>:OLATATA_DB.xlsx > restaurado.xlsx
```

`restaurado.xlsx` queda en tu disco. Para que vuelva a ser la versión
"vigente" en GitHub (y que la app la recoja), tienes dos caminos:

1. **Commit normal**: copia `restaurado.xlsx` sobre `OLATATA_DB.xlsx`
   dentro del clon, `git add`, `git commit`, `git push` a `main` — esto
   crea un commit NUEVO cuyo contenido es idéntico al de `<hash>`, con
   un SHA nuevo (GitHub nunca "mueve" un commit viejo al final; siempre
   agrega uno nuevo). Luego reinicia la app (ver arriba).
2. **API de contenidos de GitHub** (lo que hace `core/storage.py`
   internamente): un `PUT` a
   `https://api.github.com/repos/GIUSEPPESAN21/OlaTata-Database/contents/OLATATA_DB.xlsx`
   con `content` = el `.xlsx` restaurado en base64 y `sha` = el SHA
   *actual* del archivo en GitHub (consíguelo con un `GET` al mismo
   endpoint justo antes — no el `sha` del commit viejo que estás
   restaurando). Útil si prefieres un script en vez de clonar el repo.

### Opción B — revertir con la API de contenidos directamente

Si no quieres clonar nada, puedes hacer el `GET`+`PUT` de la opción A
paso 2 con `curl`/`requests` usando el mismo fine-grained PAT del paso 1
(con permiso `Contents: Read and write` sobre `OlaTata-Database`, que ya
tienes configurado). El resultado es exactamente el mismo commit que
produciría la opción A: un commit nuevo con el contenido restaurado.

En ambos casos, **siempre reinicia la app de Streamlit después** para
que su `Storage` en memoria no intente comparar contra un SHA que ya no
existe.
