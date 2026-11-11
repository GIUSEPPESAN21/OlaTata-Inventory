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

## 4. Primer arranque

Al abrir la app por primera vez, el asistente de primer arranque crea el
usuario administrador con una contraseña temporal y obliga a cambiarla antes
de continuar.
