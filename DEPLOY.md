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

> Pendiente de completar en el hito M6 con los pasos exactos de la consola
> (crear la app, apuntar a `app.py`, seleccionar rama `main`, pegar los
> secretos) y la nota sobre repo privado vs. público si la plataforma no
> permite desplegar desde un repositorio privado en esta cuenta.

## 4. Primer arranque

Al abrir la app por primera vez, el asistente de primer arranque crea el
usuario administrador con una contraseña temporal y obliga a cambiarla antes
de continuar.
