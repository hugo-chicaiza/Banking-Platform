# Guía de instalación

De cero a la aplicación corriendo en tu máquina. Documento de F-02
([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16)), criterio
de aceptación «`backend/` y `frontend/` arrancan en local siguiendo su README».

Tiempo estimado la primera vez: 20–30 minutos, casi todo descargas.

## 1. Herramientas

| Herramienta | Versión | Comprobar con | Dónde conseguirla |
| --- | --- | --- | --- |
| Git | cualquiera reciente | `git --version` | <https://git-scm.com/downloads> |
| Python | `3.14` o superior | `python --version` | <https://www.python.org/downloads/> |
| Node.js | `22.22.3+`, `24.15+` o `26+` | `node --version` | <https://nodejs.org/> |
| Docker Desktop | cualquiera reciente | `docker --version` | <https://www.docker.com/products/docker-desktop/> |
| Driver ODBC 18 para SQL Server | 18 | ver abajo | <https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server> |

**Las versiones no son una recomendación.** Angular 22 no arranca con Node 20 y
el backend usa sintaxis de Python 3.14. Si tienes varias versiones de Node
instaladas, usa un gestor (`nvm-windows`, `fnm`, `volta`) en lugar de cambiar la
del sistema.

Comprobar el driver ODBC:

```powershell
# Windows
Get-OdbcDriver | Where-Object Name -like '*SQL Server*' | Select-Object Name
```

```shell
# Linux / macOS
odbcinst -q -d
```

Debe aparecer `ODBC Driver 18 for SQL Server`. **No hace falta** para ejecutar
las pruebas ni para que el CI pase; hace falta para conectarse a SQL Server.

## 2. Clonar

```shell
git clone https://github.com/hugo-chicaiza/Banking-Platform.git
cd Banking-Platform
git switch develop
```

Se trabaja desde `develop`, no desde `main`. Ver
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## 3. Base de datos local

Desde la raíz del repositorio:

```powershell
Copy-Item .env.example .env
```

Abre `.env` y pon una contraseña en `MSSQL_SA_PASSWORD`. **Requisitos de SQL
Server:** mínimo 8 caracteres, con mayúsculas, minúsculas, dígitos y un
símbolo. Si no los cumple, el contenedor arranca y muere sin decir por qué.

Generar una:

```powershell
# Windows
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 20 | ForEach-Object {[char]$_}) + '!aA1'
```

```shell
# Linux / macOS
echo "$(openssl rand -base64 18)!aA1"
```

Levantar:

```shell
docker compose up -d sqlserver db-init
docker compose logs -f db-init     # Ctrl+C cuando diga "Inicialización terminada"
```

Crea `CooperativaDB` y `SeguridadDB` **vacías**. El esquema es alcance de F-08
([#108](https://github.com/hugo-chicaiza/Banking-Platform/issues/108)) y la
semilla de F-07
([#107](https://github.com/hugo-chicaiza/Banking-Platform/issues/107)).

> **Nota:** `MSSQL_SA_PASSWORD` del `.env` de la raíz configura el **motor**.
> `COOPERATIVA_DB_PASSWORD` y `SEGURIDAD_DB_PASSWORD` del `Backend/.env` son
> con qué se **conecta** la aplicación. En local coinciden, pero son dos cosas
> distintas, y en un entorno real la aplicación no usa `sa`.

## 4. Backend

```shell
cd Backend

python -m venv .venv
```

```powershell
# Windows
.\.venv\Scripts\Activate.ps1
```

```shell
# Linux / macOS
source .venv/bin/activate
```

> Si PowerShell rechaza el script de activación:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

```shell
pip install -r requirements-dev.txt
```

> `requirements-dev.txt` ya incluye `requirements.txt`. El CI lo instala con
> `--require-hashes --only-binary :all:`, que verifica cada paquete por su
> hash y no ejecuta ningún `setup.py`. Para regenerar los lockfiles tras tocar
> un `.in`:
>
> ```shell
> pip-compile --generate-hashes requirements.in
> pip-compile --generate-hashes requirements-dev.in
> ```

Configurar:

```powershell
Copy-Item .env.example .env
```

Para trabajar contra el SQL Server local, en `Backend/.env`:

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8471

DB_AUTH_MODE=sql
DB_TRUST_SERVER_CERTIFICATE=yes      # solo en local, ver nota

COOPERATIVA_DB_SERVER=localhost
COOPERATIVA_DB_USER=sa
COOPERATIVA_DB_PASSWORD=<la misma contraseña del .env de la raíz>

SEGURIDAD_DB_SERVER=localhost
SEGURIDAD_DB_USER=sa
SEGURIDAD_DB_PASSWORD=<la misma contraseña del .env de la raíz>
```

> **`DB_TRUST_SERVER_CERTIFICATE=yes` es aceptable solo aquí**, porque el
> contenedor de SQL Server usa un certificado autofirmado. En Azure tiene que
> quedarse en `no`: aceptar cualquier certificado anula el cifrado frente a un
> intermediario — la conexión va cifrada, pero contra quien sea.
>
> **En Azure la forma recomendada es `DB_AUTH_MODE=managed_identity`**, que usa
> Entra ID y no necesita usuario ni contraseña. Si no hay credencial, no hay
> credencial que robar ni que rotar.

Arrancar:

```shell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8471
```

> El puerto es **8471**, no el 8000 habitual, y escucha solo en `127.0.0.1`.
> Está así a propósito: un puerto no estándar en loopback no queda expuesto al
> resto de la red ni a los escaneos automáticos. En Azure se usa
> `APP_HOST=0.0.0.0` con `WEBSITES_PORT=8471`.

| URL | Qué esperar |
| --- | --- |
| <http://127.0.0.1:8471/docs> | Swagger UI |
| <http://127.0.0.1:8471/api/v1/catalogos/paises> | Catálogo de países (F-09, en curso) |

*(parte 2 de F-02)* Se añadirán las sondas `/health` y `/ready`, y
`python -m app.core.config` para validar la configuración sin arrancar el
servidor.

## 5. Frontend

En otra terminal:

```shell
cd Frontend
npm ci
npm start
```

`npm ci`, no `npm install`: instala las versiones exactas del lockfile y falla
si `package.json` y el lock no coinciden, en lugar de traer versiones nuevas en
silencio.

Abre <http://localhost:4200>. La pantalla muestra el entorno activo y el
prefijo de la API. El layout real es alcance de F-05
([#21](https://github.com/hugo-chicaiza/Banking-Platform/issues/21)).

`ng serve` reenvía todo `/api` al backend en el puerto 8471
(`proxy.conf.json`), así que el navegador y la API comparten origen y no hace
falta CORS en desarrollo.

### Sin backend

Cuando F-01 publique el mock:

```shell
docker compose --profile mock up -d
cd Frontend && npm run start:mock
```

## 6. Comprobar que todo funciona

Antes de tu primer PR, pasa la verificación completa. Es lo mismo que ejecuta
el CI.

```shell
# Backend (con el entorno virtual activado)
cd Backend
ruff format --check .
ruff check .
pytest tests
```

Esperado: sin hallazgos de formato ni de lint, y las pruebas de `Backend/tests` en verde.

```shell
# Frontend
cd Frontend
npm run verify
```

Esperado: formato correcto, sin errores de lint ni de tipos, pruebas en verde,
y los tres entornos compilados.

## 7. Editor

Instala la extensión de **EditorConfig**: `.editorconfig` configura
indentación, finales de línea y codificación en todos los editores, sin que
tengas que ajustarlos a mano.

**VS Code** — extensiones recomendadas:

| Extensión | Para qué |
| --- | --- |
| `charliermarsh.ruff` | Formato y lint de Python al guardar |
| `ms-python.python` + `ms-python.vscode-pylance` | Python y tipos |
| `angular.ng-template` | Plantillas de Angular |
| `dbaeumer.vscode-eslint` | ESLint |
| `esbenp.prettier-vscode` | Prettier |
| `editorconfig.editorconfig` | EditorConfig |

## Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| `ModuleNotFoundError: No module named 'app'` | Estás fuera de `Backend/` o sin el entorno virtual activado. |
| `Can't open lib 'ODBC Driver 18 for SQL Server'` | El driver no está instalado, o su nombre no coincide con `DB_DRIVER`. Comprobar con `Get-OdbcDriver` / `odbcinst -q -d`. |
| El backend arranca pero falla al consultar | Falta una variable en `Backend/.env`. Compárala con `Backend/.env.example`. |
| El contenedor de SQL Server arranca y muere | Casi siempre la contraseña de `sa` no cumple los requisitos. `docker compose logs sqlserver`. |
| El backend no alcanza la base | Revisa `COOPERATIVA_DB_*` y `SEGURIDAD_DB_*`, y que el contenedor esté arriba (`docker compose ps`). |
| `npm ci` falla con `EUSAGE` | `package-lock.json` desincronizado. `npm install` y sube el lock en tu PR. |
| El frontend no alcanza la API | ¿Está el backend en el 8471? Comprueba `proxy.conf.json`. |
| `ng serve` falla por la versión de Node | `node --version` contra el `engines` de `Frontend/package.json`. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| Diffs con el archivo entero cambiado | Finales de línea. `.gitattributes` lo resuelve; si ya pasó: `git add --renormalize .` |
| El CI falla y en local pasa | Compara versiones de Node y Python con `engines` y `requires-python`. Es la causa en la gran mayoría de los casos. |

## Qué leer después

1. [CONTRIBUTING.md](../../CONTRIBUTING.md) — ramas, commits y PR.
2. [Frontend/README.md](../../Frontend/README.md) si vas al frontend;
   `Backend/.env.example` y `Backend/app/` si vas al backend.
3. [SECURITY.md](../../SECURITY.md) — las cinco reglas al escribir código.
4. La ficha de tu historia en `GitHubProject_Files/`.
