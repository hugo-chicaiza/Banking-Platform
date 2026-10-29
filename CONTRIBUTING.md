# Cómo contribuir

Convenciones de trabajo del equipo. Formaliza lo que ya describía el README y
añade lo que F-02 ([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16))
necesitaba dejar por escrito: ramas, commits, revisión y protección de `main`.

Las reglas que se pueden verificar las verifica el CI
([`pr-governance.yml`](.github/workflows/pr-governance.yml)). Las que no, se
revisan en el PR.

## Antes de empezar

1. Coge una tarjeta de **To Do** en el
   [tablero](https://github.com/users/hugo-chicaiza/projects/4) y asígnatela.
2. Muévela a **In Progress**. La columna es el estado real: una tarjeta que
   nadie mueve hace que el resto del equipo trabaje con información falsa.
3. Lee la ficha del issue completa, incluidas **Dependencias**. Si la historia
   requiere otra que no está cerrada, dilo en el issue antes de empezar: puede
   que haya que reordenar.

## Ramas

Una rama por historia. Nunca se trabaja directo sobre `main` ni `develop`.

| Área | Convención | Ejemplo |
| --- | --- | --- |
| Backend | `feat/backend-<issue>-<nombre>` | `feat/backend-50-crear-cliente` |
| Frontend | `feat/frontend-<issue>-<nombre>` | `feat/frontend-21-layout-base` |
| Infraestructura, CI, configuración | `chore/<issue>-<nombre>` | `chore/16-setup-entornos-ci` |
| QA | `test/<nombre>` | `test/flujo-deposito-atm` |
| Documentación | `docs/<nombre>` | `docs/actualizar-roadmap` |
| Corrección | `fix/<nombre>` | `fix/calculo-mora-redondeo` |
| Urgencia en producción | `hotfix/<nombre>` | `hotfix/sesion-no-expira` |

> **`chore/` es nuevo.** F-02 lo añadió porque su trabajo —configuración,
> entornos y CI— no es ni backend ni frontend, y forzarlo a `feat/backend-*`
> habría descrito mal el cambio. El CI acepta los siete formatos.

```shell
git switch develop
git pull
git switch -c feat/backend-50-crear-cliente
```

## Commits

[Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/). El
**título del PR** debe seguir el mismo formato, porque la integración a `main`
es con *squash* y ese título es lo que queda en el historial.

| Tipo | Para qué |
| --- | --- |
| `feat` | Funcionalidad nueva |
| `fix` | Corrección de un defecto |
| `chore` | Mantenimiento, dependencias o configuración |
| `docs` | Documentación |
| `test` | Pruebas |
| `refactor` | Reorganización sin cambio de comportamiento |
| `perf` | Mejora de rendimiento |
| `ci` | Integración continua |

```
feat(backend): valida la cédula con el algoritmo módulo 10

El registro aceptaba cédulas con dígito verificador incorrecto, lo que
dejaba entrar clientes imposibles de validar contra el Registro Civil.

Closes #51
```

El cuerpo explica **por qué**, no qué: el qué ya está en el diff.

## Pull request

1. Antes de abrirlo, pasa la verificación local completa:

   ```shell
   # Backend
   cd Backend && ruff format --check . && ruff check . && pytest tests

   # Frontend
   cd Frontend && npm run verify
   ```

   Es exactamente lo que ejecuta el CI. Hacerlo en local evita el ciclo de
   «subo, falla, corrijo, subo» que consume minutos de runner y tiempo de todos.

2. Abre el PR **hacia `develop`**. Solo las liberaciones y los `hotfix` van
   directo a `main`.

3. Rellena la plantilla. La sección de seguridad no es decorativa: sus tres
   casillas son las formas más habituales de introducir un problema grave en
   esta aplicación.

4. Deja el PR en **Draft** mientras trabajas. Pasarlo a *Ready for review* es
   la señal de que está listo; si no, quien revise pierde el tiempo con código
   que vas a cambiar.

5. Al integrarse, mueve la tarjeta a **Ready for QA**. Regla del tablero
   (F-06): **nada pasa a Done sin pasar por Ready for QA.**

### Cómo se integra

| Destino | Estrategia | Por qué |
| --- | --- | --- |
| `develop` | *Merge commit* | Conserva los commits de la historia, útiles para entender cómo se llegó a la solución. |
| `main` | *Squash* | Un commit por historia. El historial de `main` se lee como una lista de lo que se entregó. |

## Revisión

**Si revisas:**

- Lee el diff completo. Aprobar un PR es decir «entendí lo que hace»; si no lo
  entendiste, pregunta. Preguntar es parte de revisar, no una molestia.
- Comprueba que hay pruebas de lo que se añadió, y que prueban el
  comportamiento, no la implementación.
- En código que mueve dinero, busca específicamente: ¿qué pasa con monto cero
  o negativo? ¿con dos peticiones a la vez? ¿si falla a mitad de la
  transacción?
- Distingue lo que **bloquea** de lo que es **sugerencia**. Dilo explícitamente;
  un comentario ambiguo deja a quien escribió el código sin saber si puede
  integrar.

**Si te revisan:**

- Responde a cada comentario, aunque sea «hecho» o «no lo cambio, por esto».
- Un comentario que no entiendas es una pregunta, no un ataque.

## Protección de `main`

`main` está protegida. En la práctica:

- No se puede hacer `git push` directo: todo entra por PR.
- Un PR necesita **una aprobación** y el **CI en verde**.
- No se puede forzar el historial (`--force`) ni borrar la rama.

La configuración exacta, con el motivo de cada regla y cómo aplicarla, está en
[`docs/08-Quality/Branch-Protection.md`](docs/08-Quality/Branch-Protection.md).

## Qué nunca entra al repositorio

- Archivos `.env`, certificados, claves privadas, perfiles de publicación de
  Azure. `.gitignore` los cubre, `gitleaks` los bloquea en el CI y
  `pr-governance.yml` los rechaza.
- Contraseñas, PIN, PAN, tokens o cédulas reales, ni en el código, ni en las
  pruebas, ni en la documentación.
- `node_modules/`, `.venv/`, `dist/`, artefactos de compilación.
- Respaldos de base de datos: si se tomaron de un entorno con datos de
  clientes, contienen datos personales reales.

**Si una credencial llega a un commit, hay que rotarla.** Borrar el archivo no
la quita del historial. Ver [`SECURITY.md`](SECURITY.md).

## Estándares de código

No son preferencias de estilo: cada regla responde a un defecto concreto que se
puede producir en esta aplicación. El detalle y el motivo están en
[`Frontend/README.md`](Frontend/README.md) y, para el backend, en los
comentarios de `Backend/app/core/` y en `Backend/.env.example`.

### Backend

- **Ruff** formatea y linta; **pyright** comprueba tipos. El CI
  verifica; no modifica.
- `router.py` → HTTP. `service.py` → reglas. `repository.py` → SQL.
  No se mezclan.
- **Toda** consulta usa parámetros enlazados. Una cadena interpolada en una
  consulta es una inyección SQL.
- Nada de `print()`. Se usa `get_logger()`, que enmascara los datos sensibles.
- Un secreto nuevo se declara en `Settings` como `SecretStr`, se documenta en
  `.env.example` sin valor, y se añade al validador si es obligatorio en
  staging y producción.

### Frontend

- **Prettier** formatea; **ESLint** con reglas tipadas linta; `strict` de
  TypeScript activo con ocho banderas adicionales.
- Nada de `console.*`: la consola del navegador la lee el usuario.
- `localStorage` y `sessionStorage` están bloqueados por el linter: un token
  guardado ahí queda expuesto a cualquier XSS.
- `bypassSecurityTrust*` está bloqueado: desactiva el saneado de Angular.
- Las llamadas HTTP se manejan siempre. Una promesa sin manejar puede perder en
  silencio el resultado de una operación de dinero.

## Si algo no funciona

| Síntoma | Dónde mirar |
| --- | --- |
| El CI falla y en local pasa | Compara versiones de Node y Python con las de `engines` y `requires-python`. |
| `npm ci` falla | `package-lock.json` desincronizado: `npm install` y sube el lock. |
| El backend no arranca | Revisa `Backend/.env` contra `Backend/.env.example`. |
| El backend no alcanza la base | Revisa `COOPERATIVA_DB_*`, `SEGURIDAD_DB_*` y que SQL Server esté arriba. |
| `gitleaks` marca algo que no es un secreto | Añade la excepción en `.gitleaks.toml` **explicando por qué** en el PR. |
| El contenedor de SQL Server muere al arrancar | `docker compose logs sqlserver`. Casi siempre es la contraseña de `sa`. |

Guía completa: [`docs/06-Development/Setup-Guide.md`](docs/06-Development/Setup-Guide.md).
