# Puertas de calidad

Qué verifica el CI, con qué umbral y **por qué ese umbral**. Documento de F-02
([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16)).

La regla general: un control que no se puede justificar se quita. Un control
que el equipo desactiva cada vez que molesta es peor que no tenerlo, porque da
una sensación de seguridad que no existe.

> **Alcance de este documento.** F-02 se entrega en dos partes. Esta es la
> **parte 1**: CI, frontend, gobernanza y entornos locales. El endurecimiento
> del backend (validación de configuración por entorno, enmascarado de logs,
> identificador de traza, ProblemDetails, sondas) llega en la **parte 2**, que
> se construye sobre el `Backend/` que ya existe en `develop`. Los apartados
> marcados *(parte 2)* todavía no están activos.

## Punto de partida: el CI nunca había ejecutado un control

Antes de esta entrega, el estado real era:

| Hecho | Evidencia |
| --- | --- |
| `backend-ci.yml` y `frontend-ci.yml` estaban **vacíos** (0 bytes) desde `ca1488e` hasta `9e8bd1f` | `git cat-file -s 9e8bd1f:.github/workflows/backend-ci.yml` → `0` |
| Por eso las ejecuciones #5 a #14 fallaron todas con `No event triggers defined in 'on'` | pestaña Actions |
| Recibieron contenido en `8dd6d47` (PR #222), pero desde entonces la única ejecución fue la #15, **omitida** | Actions → Backend CI #15, rama `feature/docs-1-update` |
| El despliegue a Azure falló 3 de 3 veces | Actions → «Build and deploy Python app to Azure Web App» #1, #2, #3 |

No es una crítica al trabajo anterior —los workflows se añadieron antes de que
hubiera código que verificar— pero sí es el punto de partida real.

### El agujero que cierra esta entrega

Los jobs se filtraban por **nombre de rama**:

```yaml
if: github.event_name != 'pull_request' ||
    startsWith(github.head_ref, 'feat/backend-')
```

Un PR desde `fix/`, `hotfix/`, `docs/`, `test/` o `chore/` —cinco de los siete
carriles de la convención— no ejecutaba nada. Y **GitHub cuenta un job omitido
como satisfecho** a efectos de una verificación obligatoria de rama: en cuanto
se activara la protección de `main`, esos PR se habrían integrado con el CI «en
verde» sin correr ni un linter.

La corrección tiene dos formas, según el workflow:

| Workflow | Corrección | Por qué esa y no la otra |
| --- | --- | --- |
| `backend-ci.yml` | Se elimina el filtro y el job corre en **todo** PR a `main` y `develop`, sin filtro de ruta | Cada paso ya comprueba por su cuenta si hay algo que analizar (`if find ... else SKIPPED`), así que un PR que no toca el backend sigue siendo barato pero devuelve un resultado **real** |
| `frontend-ci.yml` | Filtros por **ruta** + un job agregador final | Los pasos de Angular no son baratos en vacío (`npm ci`), así que conviene saltarlos; el agregador traduce «omitido» a éxito de forma explícita y auditable |

> **Qué NO se tocó de `backend-ci.yml`.** Los pasos se dejan íntegros, incluido
> el endurecimiento que introdujo el PR #227: `pip install --require-hashes
> --only-binary :all:` (Sonar S8541/S8544) y `gitleaks-action` fijado por SHA
> (S7637). Las dos medidas son mejores que las que traía `main` y se conservan.

### Verificaciones obligatorias

Estas son las que hay que marcar en la protección de rama, por su nombre exacto:

```
Backend Quality and Security
Frontend CI
Convenciones de rama y título
Contenido del PR
```

`Frontend CI` es el **job agregador** del final de `frontend-ci.yml`: tiene
`if: always()` y `needs: [todos los demás]`, y evalúa el resultado de cada uno
traduciendo «omitido» a éxito de forma explícita. Marcar los jobs individuales
reabriría el agujero descrito arriba.

> Los checks solo aparecen en el desplegable de GitHub **después** de haberse
> ejecutado al menos una vez. Secuencia: integrar este PR → dejar que el CI
> corra → volver a `Branch-Protection.md` y añadirlos.

## Qué corre en cada pull request

| Workflow | Cuándo | Bloquea |
| --- | --- | --- |
| [`backend-ci.yml`](../../.github/workflows/backend-ci.yml) | todo PR a `main`/`develop` | sí |
| [`frontend-ci.yml`](../../.github/workflows/frontend-ci.yml) | PR que toca `Frontend/**` | sí |
| [`pr-governance.yml`](../../.github/workflows/pr-governance.yml) | todo PR | sí (rama, título, archivos prohibidos) |
| [`dependency-review.yml`](../../.github/workflows/dependency-review.yml) | todo PR | **no todavía** — ver abajo |
| [`codeql.yml`](../../.github/workflows/codeql.yml) | todo PR + lunes 06:00 UTC | no (informa en Security) |
| [`openapi-ci.yml`](../../.github/workflows/openapi-ci.yml) | PR que toca el contrato | sí (cuando el contrato exista) |

## Frontend — 11 controles

| # | Control | Umbral | Bloquea |
| --- | --- | --- | :-: |
| 1 | `prettier --check` | sin diferencias | ✅ |
| 2 | `eslint` con reglas **tipadas** | cero errores | ✅ |
| 3 | `tsc -b --noEmit` | cero errores | ✅ |
| 4 | Vitest sobre jsdom | todas pasan | ✅ |
| 5 | Cobertura | ≥ 80 % líneas, ≥ 70 % ramas | ✅ |
| 6 | **Compila los TRES entornos** | correcta | ✅ |
| 7 | **CSP estricta presente en el HTML** | `strict-dynamic` | ✅ |
| 8 | Presupuesto de bundle | 1 MB inicial | ✅ |
| 9 | `npm audit --omit=dev` | cero `high` | ✅ |
| 10 | `npm audit` (desarrollo) | informa | — |
| 11 | Lockfile sincronizado | correcto | ✅ |

Los dos que más aportan:

- **#6 compila los tres entornos.** Una configuración de entorno rota solo falla
  al compilar *esa* configuración; descubrirlo en el despliegue a staging es tarde.
- **#7 verifica la CSP.** Si alguien quita `security.autoCsp` de `angular.json`,
  el build sigue pasando y la protección desaparece en silencio. El paso falla:

  ```yaml
  grep -q "strict-dynamic" dist/frontend/browser/index.html \
    || { echo "::error::La CSP no es estricta"; exit 1; }
  ```

Y un detalle de cadena de suministro: **los cuatro jobs instalan con
`npm ci --ignore-scripts`**, para que los scripts de instalación de ninguna
dependencia transitiva ejecuten código arbitrario en el runner — el vector
habitual de los ataques a npm (`githubactions:S6505`).

> La primera versión solo lo ponía en el job de calidad, suponiendo que
> `esbuild` necesitaba su script de instalación para resolver el binario de la
> plataforma. **Es falso:** lo resuelve por dependencias opcionales. Con un
> `node_modules` limpio y `--ignore-scripts`, la compilación de los tres
> entornos y las pruebas pasan igual. Lo señaló SonarQube y se comprobó en
> local antes de cambiarlo.

## Backend — lo que corre hoy

Los pasos actuales de `backend-ci.yml`, sin cambios respecto a `develop`:

| Control | Herramienta |
| --- | --- |
| Formato | `ruff format --check Backend` |
| Lint | `ruff check Backend` |
| Sintaxis | `python -m compileall` |
| Tipos | `pyright Backend` |
| Pruebas | `pytest Backend/tests` |
| Seguridad del código | `bandit -r Backend -x Backend/tests` |
| Dependencias | `pip-audit -r Backend/requirements.txt` |
| Credenciales | `gitleaks-action` (fijado por SHA) |
| Instalación verificada | `pip --require-hashes --only-binary :all:` |

*(parte 2)* Se añadirán: umbral de cobertura, `mypy --strict`, validación del
arranque con configuración de producción, construcción de la imagen con
comprobación de que arranca y **de que no corre como root**, `trivy` sobre la
imagen y SBOM.

## Sobre la cobertura del 80 %

**Qué significa y qué no.** El 80 % no es un objetivo de calidad: es un suelo
que detecta código que nadie ejecutó nunca. Una prueba que llama a una función
y no comprueba nada sube la cobertura y no vale nada.

Lo que de verdad se pide en la revisión del PR: **que la prueba falle si el
comportamiento cambia.** Eso lo verifica una persona, no una herramienta.

**Por qué 80 y no 100.** Llegar al 100 obliga a escribir pruebas de los caminos
que no importan —el `if __name__ == "__main__"`, el `except` que no se puede
provocar— y eso enseña al equipo a escribir pruebas para la métrica en lugar de
para el riesgo.

**Qué se excluye de la medición, y por qué:**

| Excluido | Motivo |
| --- | --- |
| `Backend/app/modules/*/repository.py` | SQL puro. Se cubre con pruebas de integración contra una base real (F-06) |
| `Backend/app/main.py`, `Frontend/src/main.ts` | Son el arranque. Se prueban arrancando la aplicación |
| `Frontend/src/environments/**` | Constantes. Cubrirlas no demuestra nada |

**Cómo cambiarlo.** Subirlo es decisión de F-06
([#22](https://github.com/hugo-chicaiza/Banking-Platform/issues/22)). Bajarlo
requiere acuerdo del equipo **y** que quede escrito aquí con el motivo. Un
umbral que se baja en silencio en un PR deja de ser un control.

## SonarQube

### Qué aporta

Las demás herramientas dan el estado de **hoy**. Sonar mide la **tendencia** y
aplica la regla del **código nuevo**: no exige arreglar la deuda que ya existe,
exige que lo que se añade cumpla el estándar. Es lo que hace sostenible la
calidad en un proyecto de meses sin frenar el avance.

### Puesta en marcha

Mientras no exista el secreto `SONAR_TOKEN`, el job del CI **se omite con un
aviso**, no falla. Así esta entrega se puede integrar sin esperar a quien tenga
permisos de administración.

1. Entrar en <https://sonarcloud.io> con la cuenta de GitHub.
2. **Analyze new project** → `hugo-chicaiza/Banking-Platform`. Gratuito para
   repositorios públicos.
3. **Analysis Method** → **desactivar *Automatic Analysis***. Es imprescindible:
   si queda activo, Sonar analiza por su cuenta sin los informes de cobertura
   que genera el CI y los porcentajes salen en cero.
4. Copiar el `projectKey` y el `organization` que asigna Sonar y ponerlos en
   [`sonar-project.properties`](../../sonar-project.properties). **Los valores
   actuales son una conjetura y hay que confirmarlos.**
5. Generar un token en **My Account → Security**.
6. Guardarlo como secreto del repositorio con el nombre `SONAR_TOKEN`.
7. Con **SonarQube Server** autoalojado en lugar de Cloud, añadir también
   `SONAR_HOST_URL`.

### Puerta de calidad acordada

Los umbrales se configuran en la interfaz de Sonar, sobre el **código nuevo**:

| Métrica | Umbral | Por qué |
| --- | --- | --- |
| Cobertura del código nuevo | ≥ 80 % | Mismo criterio que el CI local |
| Duplicación del código nuevo | ≤ 3 % | Una regla de negocio copiada se corrige en un sitio y se olvida en el otro. En cálculo de intereses o de mora, **eso es una diferencia de dinero** |
| Security hotspots revisados | 100 % | Un *hotspot* no es un defecto: es algo que alguien tiene que mirar. Lo que no se admite es dejarlo sin revisar |
| Vulnerabilidades nuevas | 0 | — |
| Bugs nuevos | 0 | — |
| Calificación de mantenibilidad | A | Sobre el código nuevo, no sobre el proyecto |

> **Estos umbrales están escritos aquí a propósito.** Viven en la interfaz de
> Sonar, donde se pueden cambiar sin que aparezca en ningún PR. Tenerlos en el
> repositorio hace que un cambio sea visible y revisable.

## Revisión de dependencias — pendiente de un ajuste del repositorio

`dependency-review.yml` mira el **diff** del PR y señala la dependencia que se
está **añadiendo**, con su vulnerabilidad y su licencia. Es distinto de
`pip-audit` y `npm audit`, que auditan lo que ya hay: el valor está en avisar
*antes* de integrar, cuando quitar la dependencia cuesta un commit y no cuando
ya hay código que la usa.

> [!WARNING]
> **Hoy este control informa pero no protege.** La acción responde:
>
> ```
> Dependency review is not supported on this repository.
> Please ensure that Dependency graph is enabled.
> ```
>
> El **grafo de dependencias** del repositorio está desactivado. Se activa en
> **Settings → Security and analysis → Dependency graph** y requiere permisos
> de administración.
>
> Mientras tanto el paso lleva `continue-on-error: true`, para que un ajuste
> que nadie con permisos ha tocado no deje en rojo todos los PR del
> repositorio. El job deja un aviso visible en el resumen para que un job
> verde no se confunda con una revisión hecha.
>
> **Al activar el grafo hay que quitar el `continue-on-error`** de
> `.github/workflows/dependency-review.yml`. Está marcado con un comentario en
> el propio archivo.

Cuando esté activo bloqueará por:

| Motivo | Umbral |
| --- | --- |
| Vulnerabilidad en una dependencia que el PR añade | severidad `high` o superior |
| Licencia vetada | `GPL-2.0-only`, `GPL-2.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later`, `AGPL-3.0-only`, `AGPL-3.0-or-later` |

Las licencias vetadas obligan a publicar el código fuente del software que las
enlaza. No es una opinión sobre ellas, es una restricción del modelo de
negocio. `SSPL-1.0` también lo estaría, pero **no es un identificador SPDX**
(no está aprobada por la OSI) y la acción no lo admite; si alguna vez entra una
dependencia con SSPL habrá que detectarla en la revisión del PR.

> Dos detalles de configuración que hacen fallar la acción **sin revisar
> nada**, y que cuestan tiempo de diagnosticar porque el mensaje es el mismo
> («Invalid license(s)»):
>
> 1. `deny-licenses` se parsea como lista **separada por comas**. Un bloque
>    YAML `|` llega como una sola cadena con saltos de línea y se rechaza
>    entera.
> 2. Los identificadores tienen que ser SPDX **vigentes**: `GPL-3.0` y
>    `AGPL-3.0` a secas están obsoletos.

## CodeQL

Análisis de flujo de datos **entre** archivos y funciones. Es la diferencia con
ruff, bandit y eslint, que miran patrones dentro de un archivo.

El caso que detecta y los demás no: un valor que entra por un parámetro HTTP,
pasa por tres funciones y llega sin validar a una consulta SQL.

- Conjunto de consultas: `security-extended`. En una aplicación que mueve
  dinero, revisar algún falso positivo cuesta menos que no detectar un flujo
  sin validar.
- Gratuito en repositorios públicos. **Si el repositorio pasa a privado,
  requiere GitHub Advanced Security**; en ese caso hay que desactivar el
  workflow y anotarlo aquí.
- No bloquea: informa en Security → Code scanning y comenta en la línea
  afectada. Se podrá hacer bloqueante cuando el equipo tenga el hábito de
  atender las alertas.

## Fijación de versiones

Todo está fijado: dependencias, acciones de GitHub, herramientas, imagen base.

| Qué | Cómo | Dónde |
| --- | --- | --- |
| Dependencias Python | `==` exacto + hashes | `Backend/requirements*.txt` |
| Dependencias npm | versión exacta + `package-lock.json` | `Frontend/package.json` |
| Acciones de GitHub | etiqueta de versión exacta o SHA | `.github/workflows/*.yml` |
| Herramientas en los workflows | versión exacta | en cada paso |

**Etiqueta frente a SHA: el criterio acordado.** Fijar por SHA (`@a1b2c3d…`)
es más estricto, porque una etiqueta se puede mover a otro commit y un SHA no.
La contrapartida es que el workflow se vuelve menos legible.

La regla del repositorio, que es la que aplica SonarQube
(`githubactions:S7637`):

| Quién publica la acción | Cómo se fija | Ejemplo |
| --- | --- | --- |
| GitHub (`actions/*`, `github/*`) | **Etiqueta** de versión exacta | `actions/checkout@v7.0.1` |
| **Cualquier tercero** | **SHA completo**, con la versión en un comentario | `amannn/action-semantic-pull-request@48f2562… # v6.1.1` |

El razonamiento: una acción de terceros es código ajeno que se ejecuta con
acceso al repositorio y al token. Si quien la publica mueve la etiqueta —o
pierde el control de su cuenta— el SHA es lo único que impide que ese cambio
entre en el CI sin que nadie lo revise. Es la categoría **OWASP Top 10:2025
A03 — Software Supply Chain Failures**.

Para las acciones de GitHub la etiqueta basta: el riesgo de que `actions/*`
mueva una etiqueta de forma maliciosa no es comparable, y la legibilidad sí
importa.

Dependabot actualiza ambas formas, incluidos los SHA.

**Cómo obtener el SHA de una etiqueta:**

```shell
gh api repos/amannn/action-semantic-pull-request/git/ref/tags/v6.1.1 --jq .object.sha
```

(Si el objeto es de tipo `tag` y no `commit`, hay que resolverlo una vez más
con `git/tags/<sha>`; son las etiquetas anotadas.)

## Lo que NO verifica el CI

Importante tenerlo claro para no confiar en lo que no está:

| No se verifica | Por qué | Quién lo cubrirá |
| --- | --- | --- |
| Pruebas de integración contra SQL Server | Haría falta un SQL Server en el runner, y no hay esquema todavía | F-06, tras F-08 |
| Pruebas de contrato contra `openapi.yaml` | El contrato no existe aún | F-06, tras F-01 |
| Pruebas de extremo a extremo | No hay flujos completos que probar | F-06 |
| Que los permisos por rol se apliquen | La autenticación llega con F-03 | F-03, F-06 |
| Rendimiento y concurrencia | Importa en operaciones de dinero; no hay ninguna todavía | Épicas 2 y 3 |
| Que la lógica financiera sea correcta | Ninguna herramienta puede verificarlo | Cada épica |

El último punto es el que más conviene recordar: **el CI en verde significa que
el código cumple el estándar, no que haga lo correcto.** Para eso está la
revisión del PR y el paso por Ready for QA.

## Cuánto tarda

| Workflow | Tiempo aproximado |
| --- | --- |
| Backend CI | 2–4 min |
| Frontend CI | 3–5 min |
| Gobernanza del PR | < 1 min |
| CodeQL | 5–8 min |

Todos los jobs llevan `timeout-minutes`: un job colgado consumiría runner hasta
el límite de 6 horas de GitHub.

## Cuando un control estorba

Pasa, y hay una forma correcta de resolverlo:

1. **Si el control tiene razón**, se arregla el código. Es el caso la mayoría
   de las veces.
2. **Si es un falso positivo**, se añade la excepción **lo más acotada
   posible** y con el motivo escrito:
   - Ruff: `# noqa: REGLA` en la línea, con un comentario que explique por qué.
   - mypy: `# type: ignore[codigo]` con el código concreto, nunca desnudo.
   - ESLint: `// eslint-disable-next-line regla` con el motivo.
   - bandit: `# nosec BXXX` con el motivo.
   - gitleaks: una entrada en `.gitleaks.toml` o un fingerprint en
     `.gitleaksignore`, explicada en el PR.
3. **Si el control estorba siempre**, está mal configurado. Se abre un issue y
   se cambia la configuración, con el cambio visible en un PR.

**Lo que no se hace:** desactivar la regla para todo el archivo o para todo el
proyecto para desbloquear un PR. Eso convierte un hallazgo puntual en una
pérdida permanente de cobertura del control.
