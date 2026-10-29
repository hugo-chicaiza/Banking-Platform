# Frontend — Banking Platform

Aplicación Angular de la plataforma bancaria. Esta base la entrega **F-02 | Configuración
de proyecto, entornos y CI** ([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16)).

Lo que hay aquí es el andamiaje: el proyecto arranca, compila, se lintea, se formatea, se
prueba y se construye para tres entornos. **No** incluye el layout, el menú ni el ruteo por
rol: eso es F-05 ([#21](https://github.com/hugo-chicaiza/Banking-Platform/issues/21)), ni la
pantalla de login, que es F-03 ([#17](https://github.com/hugo-chicaiza/Banking-Platform/issues/17)).

## Requisitos

| Herramienta | Versión                              | Cómo comprobarlo |
| ----------- | ------------------------------------ | ---------------- |
| Node.js     | `^22.22.3` · `^24.15.0` · `>=26.0.0` | `node --version` |
| npm         | `>=10`                               | `npm --version`  |

Las versiones están declaradas en `engines` de `package.json`; Angular 22 no arranca con
versiones anteriores. Si tienes varias instalaciones de Node, usa un gestor de versiones
(`nvm`, `fnm`, `volta`) en lugar de cambiar la del sistema.

## Arranque local

```shell
cd Frontend
npm ci          # instala exactamente lo que fija package-lock.json
npm start       # http://localhost:4200
```

`npm ci` —no `npm install`— es lo que se usa en local y en CI: instala las versiones exactas
del lock y falla si `package.json` y el lock no coinciden, en lugar de resolver versiones
nuevas en silencio (OWASP Top 10:2025 A03 — Software Supply Chain Failures).

### Contra qué habla el frontend

`npm start` levanta `ng serve` con `proxy.conf.json`, que reenvía todo `/api` a
`http://127.0.0.1:8471`, el backend local. Así el navegador y la API comparten origen: no
hace falta CORS en desarrollo y el host del backend no queda escrito en el bundle.

Mientras el backend no exista, se puede trabajar contra el mock de F-01:

```shell
npm run start:mock      # reenvía /api/v1 al mock de Prism en el puerto 4010
```

`proxy.mock.json` quita el prefijo `/api/v1` antes de llamar al mock, porque Prism monta las
rutas tal como aparecen en `paths:` del `openapi.yaml`, sin el `servers.url`. **F-01 debe
confirmar este punto** cuando publique el mock; si lo monta con prefijo, hay que borrar el
`pathRewrite` de ese archivo.

## Comandos

| Comando                 | Qué hace                                                       |
| ----------------------- | -------------------------------------------------------------- |
| `npm start`             | Servidor de desarrollo con proxy al backend local.             |
| `npm run start:mock`    | Servidor de desarrollo con proxy al mock de F-01.              |
| `npm run lint`          | ESLint sobre `.ts` y plantillas `.html`.                       |
| `npm run lint:fix`      | Igual, corrigiendo lo que se puede corregir solo.              |
| `npm run format`        | Aplica Prettier.                                               |
| `npm run format:check`  | Verifica formato sin tocar archivos (es lo que corre el CI).   |
| `npm run typecheck`     | `tsc -b --noEmit` sobre los tres `tsconfig`.                   |
| `npm test`              | Pruebas en modo vigilancia.                                    |
| `npm run test:ci`       | Pruebas una vez, con cobertura y reporte JUnit.                |
| `npm run build`         | Compilación de producción.                                     |
| `npm run build:staging` | Compilación de staging.                                        |
| `npm run verify`        | **Todo lo anterior en orden.** Ejecútalo antes de abrir el PR. |

`npm run verify` reproduce exactamente lo que valida `frontend-ci.yml`. Si pasa en local,
pasa en el CI.

## Entornos

Un único árbol de código, tres configuraciones. `angular.json` sustituye el archivo de
entorno en tiempo de compilación (`fileReplacements`):

| Configuración | Archivo que se usa                           | Logs de depuración | Inactividad | CSP estricta |
| ------------- | -------------------------------------------- | ------------------ | ----------- | ------------ |
| `development` | `src/environments/environment.ts`            | sí                 | 60 min      | no           |
| `staging`     | `src/environments/environment.staging.ts`    | no                 | 30 min      | sí           |
| `production`  | `src/environments/environment.production.ts` | no                 | 15 min      | sí           |

Reglas:

1. **En el frontend no hay secretos.** Todo lo que se compila viaja al navegador y cualquiera
   puede leerlo. Los archivos de entorno solo llevan valores públicos: nombre del entorno,
   prefijo de la API y banderas de comportamiento. Las credenciales viven en el backend
   (`Backend/.env`, nunca versionado) y en los _secrets_ de GitHub.
2. **El código importa siempre `./environments/environment`**, nunca los archivos
   `.staging.ts` o `.production.ts` directamente: una importación directa se salta la
   sustitución y acaba con valores de desarrollo en producción. La única excepción son las
   pruebas que comparan los tres entornos entre sí.
3. Añadir un campo obliga a actualizar los tres archivos: el tipo `AppEnvironment` hace que
   `npm run typecheck` falle si se olvida uno.

## Calidad y seguridad del código

Lo que está configurado, y el motivo:

| Control                                     | Dónde                                | Para qué                                                                                                   |
| ------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `strict` + 8 banderas extra de TS           | `tsconfig.json`                      | Los `null`, los índices sin comprobar y el código muerto los detecta el compilador, no la revisión manual. |
| `strictTemplates` + diagnósticos como error | `tsconfig.json`                      | Un binding mal escrito rompe la compilación en vez de fallar en pantalla.                                  |
| `typescript-eslint` con tipos               | `eslint.config.mjs`                  | Detecta promesas sin manejar, `any` que se escapa y comparaciones imposibles.                              |
| `eslint-plugin-security`                    | `eslint.config.mjs`                  | Heurísticas de código peligroso.                                                                           |
| `no-console` como error                     | `eslint.config.mjs`                  | La consola del navegador la lee el usuario, y aquí circulan saldos y datos de tarjeta.                     |
| `localStorage`/`sessionStorage` bloqueados  | `eslint.config.mjs`                  | Un token guardado ahí queda expuesto a cualquier XSS. Dónde se guarda lo decide F-03.                      |
| `bypassSecurityTrust*` bloqueado            | `eslint.config.mjs`                  | Desactiva el saneado de Angular; si hace falta, debe justificarse en el PR.                                |
| `security.autoCsp`                          | `angular.json` (staging, producción) | Content-Security-Policy estricta por hash, generada por el compilador.                                     |
| `subresourceIntegrity`                      | `angular.json` (staging, producción) | El navegador rechaza un script alterado en tránsito o en el CDN.                                           |
| Umbrales de cobertura                       | `vitest-base.config.mts`             | 80 % líneas/sentencias/funciones, 70 % ramas. Bajarlos requiere acuerdo del equipo.                        |
| Presupuestos de bundle                      | `angular.json`                       | Un bundle que crece sin control es un fallo de build, no una sorpresa en producción.                       |

Al tocar el saneado de HTML o el almacenamiento de tokens, revisa también
[Angular — guía de seguridad](https://angular.dev/best-practices/security).

## Pruebas

El runner es **Vitest sobre jsdom**, el que trae `@angular/build:unit-test` en Angular 22.
No hace falta Chrome ni Karma, así que el CI corre sin navegador.

```shell
npm test            # vigilancia, para desarrollar
npm run test:ci     # una pasada, con cobertura y reporte JUnit
```

Salidas que consume el CI:

- `coverage/lcov.info` → SonarQube
- `coverage/cobertura-coverage.xml` → resumen en el PR
- `reports/junit.xml` → lista de pruebas fallidas en el resumen del job

Los umbrales están en `vitest-base.config.mts`. Si la cobertura baja del umbral, el comando
falla; no es una advertencia.

La estrategia completa de pruebas (niveles, contrato, integración, regresión, plantillas de
caso y de defecto) es alcance de F-06
([#22](https://github.com/hugo-chicaiza/Banking-Platform/issues/22)). F-02 solo deja el
runner, la cobertura y los reportes funcionando para que F-06 solo tenga que escribir casos.

## Estructura

```text
Frontend/
├── angular.json                  # Targets y las 3 configuraciones de entorno
├── eslint.config.mjs             # Reglas de lint (flat config)
├── vitest-base.config.mts        # Umbrales y reportes de cobertura
├── proxy.conf.json               # /api → backend local
├── proxy.mock.json               # /api/v1 → mock de Prism (F-01)
├── tsconfig.json                 # Banderas estrictas compartidas
└── src/
    ├── environments/             # environment.model.ts + los 3 entornos
    ├── index.html                # Cabeceras de seguridad que no dependen del servidor
    └── app/                      # Cáscara mínima; el layout real es F-05
```

## Antes de abrir un PR

1. `npm run verify` en verde.
2. Rama nombrada según [`CONTRIBUTING.md`](../CONTRIBUTING.md) (`feat/frontend-<issue>-<nombre>`).
3. Mensajes de commit en formato Conventional Commits.
4. Ningún `.env` ni credencial en el diff: `gitleaks` lo bloquea en el CI, pero conviene no
   llegar ahí.
