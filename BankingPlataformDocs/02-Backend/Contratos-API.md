# Piloto de contratos OpenAPI para ATM

Esta propuesta permite revisar el acuerdo entre frontend, backend y QA antes de implementar una operación. El piloto contiene **solo ATM-13**, relacionado con [T-09, issue #102](https://github.com/hugo-chicaiza/Banking-Platform/issues/102):

```http
GET /api/v1/atm/terminales/{idATM}/gavetas
```

El contrato está **propuesto para revisión**, no aprobado como convención de todo el proyecto. Este PR no implementa el endpoint ni configura CI, un servidor de mocks o una publicación web. T-09 también necesita ATM-14; aprobar este piloto no completa la historia.

## Estructura y responsabilidad de los archivos

```text
BankingPlataformDocs/
├── Home.md                        # índice existente con enlace a esta guía
└── 02-Backend/
    ├── Contratos-API.md            # uso, alcance y acuerdos de revisión
    └── openapi/
        ├── enquo-v1.yaml           # definición técnica del piloto
        └── index.html             # visor local de esa misma definición
```

- **YAML:** describe el método, la ruta, los parámetros, la seguridad, las respuestas y los tipos de datos. Es el único archivo que define técnicamente esta operación en el piloto.
- **Markdown:** explica la propuesta y cómo revisarla; no mantiene otra copia de los esquemas.
- **HTML:** carga el YAML de la rama local y lo muestra con Swagger UI. No contiene una segunda definición del contrato.
- **Home:** reutiliza el índice del espacio de Obsidian, sin reorganizar las otras áreas.

La carpeta existente de documentación sigue siendo el punto de entrada. No se añaden carpetas de aplicación, cambios de base de datos ni workflows.

## Ver el contrato en Swagger antes del merge

No hace falta que el PR esté integrado en `main`. Hay que tener localmente su rama y servir sus archivos por HTTP; abrir `index.html` con doble clic no es el flujo soportado.

### 1 Obtener la rama del PR

Desde una copia del repositorio:

```shell
git fetch origin
git switch --track origin/docs/atm-13-openapi-pilot
```

Si la rama ya existe localmente, usar `git switch docs/atm-13-openapi-pilot`. También se puede utilizar `gh pr checkout` con el número de este PR. No es necesario hacer merge ni cambiar `main`.

### 2 Iniciar un servidor de archivos

Desde la **raíz del repositorio**, con Python 3 disponible:

```shell
python -m http.server 8081 --bind 127.0.0.1 --directory BankingPlataformDocs/02-Backend/openapi
```

En Windows se puede sustituir `python` por `py -3` si ese es el comando instalado. Este proceso solo sirve los archivos de documentación; no inicia FastAPI ni se conecta a la base de datos.

### 3 Abrir la vista local

Abrir <http://127.0.0.1:8081/>. Swagger UI carga `enquo-v1.yaml` y presenta:

1. La operación ATM-13 y el identificador `atmConsultarGavetas`.
2. El parámetro de ruta requerido `idATM`.
3. La respuesta `200`, su arreglo y los ejemplos.
4. Las respuestas de error propuestas `401`, `403` y `404`.
5. Los modelos reutilizables `Gaveta`, `ProblemDetails` y `FieldError`.

El visor usa Swagger UI **5.34.0**, fijado en los enlaces del CDN y protegido con hashes de integridad. Necesita acceso a `cdn.jsdelivr.net`; no instala Swagger UI en frontend ni backend. Si el CDN está bloqueado, se verá el mensaje de carga y habrá que acordar otra distribución de esos recursos.

**«Try it out» está deshabilitado.** No es necesario introducir tokens. El visor muestra una propuesta documental; no entrega datos reales, no inicia llamadas al endpoint y no funciona como mock. También está deshabilitado el validador remoto de Swagger UI; la visualización no se usa como sustituto de una validación formal.

### 4 Revisar o detener

Al editar el YAML, guardar el archivo y recargar la página para ver el cambio. La página refleja la rama local, no automáticamente la última versión remota del PR; después de actualizar la rama hay que recargarla. Detener el servidor con `Ctrl+C`.

Si el puerto está ocupado, usar otro, por ejemplo `8082`, tanto en el comando como en el navegador. La dirección `127.0.0.1` es local a cada equipo; para la reunión se puede compartir pantalla, pero no es un enlace público para los compañeros.

## Fuente del contrato y decisiones propuestas

Fuente: [Excel del equipo](https://udlaec-my.sharepoint.com/:x:/g/personal/diego_toscano_udla_edu_ec/IQB3Mus3k-xBQoZ1rXek2J1GAdbufmAeQykeruuvYEGrC4k?e=1uHZcH), `backlog_banking_platform_v2.xlsx`:

| Ubicación | Qué respalda |
| --- | --- |
| Backlog, fila 34 | T-09 relaciona ATM-13 y ATM-14. |
| Endpoints, fila 64 | GET, ruta, roles SUPERVISOR/CAJERO/ADMIN, lectura de ATM.Gaveta y respuesta Gaveta[] con HTTP 200. |
| Esquemas, filas 377–382 | idGaveta, numeroGaveta, idDenominacion, capacidad, cantidadActual y estado A/I. Solo idGaveta está marcado requerido. |
| Esquemas, filas 2–10 | Campos de ProblemDetails y FieldError. |

Los identificadores y cantidades de los ejemplos son ficticios. No se deduce una denominación monetaria concreta a partir del identificador de ejemplo.

El equipo debe revisar estas decisiones antes de aprobar el contrato:

- Uso de JWT Bearer de **operador**, diferenciándolo del token de un cliente ATM.
- Alcance de acceso por agencia y terminal; el rol por sí solo no autoriza a consultar cualquier ATM.
- Uso de `401`, `403` y `404`, códigos de negocio y formato `application/problem+json`. Son propuestas: la fila de ATM-13 no define errores de negocio específicos.
- Obligatoriedad y nullabilidad de los campos sin marca. El piloto los modela como no obligatorios, sin permitir `null` cuando están presentes; esa interpretación no se considera aprobada.
- Respuesta vacía para un terminal que existe pero no tiene gavetas.
- Significado y reglas de los estados A e I.

El contrato no añade columnas ni tablas y no certifica que esta funcionalidad esté implementada en los SQL.

## Revisión del PR y adopción gradual

El alcance funcional es **una operación**, aunque tenga varios archivos y esquemas de apoyo. No se propone una regla permanente de un endpoint por PR. Si varias operaciones cambian juntas, puede ser más claro revisarlas en un mismo PR.

1. Frontend revisa si el contrato entrega los datos necesarios y si distingue los resultados esperados.
2. Backend revisa si las reglas, permisos, tipos y errores son implementables y coherentes con el modelo.
3. QA revisa escenarios de éxito, errores y acceso autorizado/no autorizado.
4. El equipo resuelve o modifica las decisiones anteriores antes de aprobar el acuerdo.
5. Solo si el piloto aporta valor, se extiende a ATM-14 y al resto de la épica.

La aprobación del contrato permite avanzar al desarrollo. No implementa T-09, no cierra #102 y no convierte el documento en evidencia de QA.

## Validación manual y futura integración con CI

El CI ejecutaría automáticamente una herramienta que revisa el contrato. Este PR **no modifica** los workflows actuales. Para reproducir una revisión estructural manual, con Node.js compatible (22.12 o superior) y npm 10 o superior:

```shell
npx --yes @redocly/cli@2.71.1 lint --extends spec BankingPlataformDocs/02-Backend/openapi/enquo-v1.yaml
```

La versión está fijada para este piloto. Esta revisión valida la estructura y referencias de OpenAPI; no ejecuta el endpoint, no revisa saldos ni demuestra que los roles se estén aplicando. Una futura convención puede añadir reglas editoriales, comparación de cambios incompatibles y pruebas de la implementación.

| Revisión | Qué comprueba | Qué no demuestra |
| --- | --- | --- |
| OpenAPI válido | Estructura, parámetros y referencias. | Que exista un backend funcionando. |
| Ejemplos contra sus esquemas | Que los datos ilustrativos tengan la forma declarada. | Que sean datos reales. |
| API real contra el contrato | Que la implementación entregue la estructura acordada. | Toda la lógica financiera o todos los permisos. |
| Pruebas de negocio e integración | Comportamiento, permisos, concurrencia y efectos esperados. | Se necesitan casos propios; no aparecen automáticamente al escribir YAML. |

## Relación con FastAPI y la documentación actual

El README menciona FastAPI como backend previsto. FastAPI puede generar `/openapi.json` y `/docs` desde el código. Este piloto propone **revisar primero el acuerdo**, sin esperar a implementar esa operación.

Si se mantiene FastAPI, hay que acordar cómo verificar que su descripción generada y la implementación respeten el contrato aprobado. No se propone sustituir la descripción generada de FastAPI por este archivo sin comprobar la lógica real, ni comparar ambos documentos solo por igualdad de texto. Dos especificaciones pueden diferir en organización sin describir comportamientos incompatibles.

El documento de planificación prescribe ClickUp Docs, mientras el equipo utiliza GitHub y Notion. La fuente técnica definitiva y su relación con esas herramientas requieren un acuerdo del grupo. Si se adopta OpenAPI, Word puede conservar una entrega de versión y Notion las explicaciones y enlaces; no conviene mantener varias definiciones técnicas independientes.

## Guion breve para discutirlo con el equipo

> Propongo probar una operación con un contrato que podamos revisar en GitHub antes de implementarla. El YAML declara el acuerdo; Swagger lo muestra de forma legible. El PR permite discutir cambios y decisiones. Si nos ayuda a coordinar frontend, backend y QA, lo extendemos y después acordamos la automatización.

Para mostrarlo en cinco minutos:

1. Abrir **Files changed** del PR y señalar que solo cambia documentación del área backend y el enlace del índice.
2. Mostrar el YAML: ruta, `idATM`, respuesta `200` y referencia a `Gaveta`.
3. Abrir el visor local y enseñar la misma información de forma navegable.
4. Mostrar los errores y decisiones pendientes para distinguir acuerdo propuesto de implementación real.
5. Preguntar qué cambiaría cada área antes de aprobar el piloto y si compensa mantenerlo.

### Preguntas previsibles

**¿Por qué no dejarlo únicamente en Word o Notion?** Son útiles para explicar negocio. OpenAPI añade una definición estructurada que puede validarse y alimentar herramientas; el PR permite ver qué cambió. El beneficio depende de evitar copias divergentes.

**¿No lo hace ya FastAPI?** Puede generar documentación desde el código. El valor aquí es acordar la interfaz antes de implementarla y comprobar luego su correspondencia. Si el grupo prefiere un enfoque generado desde código, debe acordarse cómo mantener el contrato estable; no hace falta adoptar este piloto a toda costa.

**¿Swagger genera el backend o un mock?** Esta configuración solo muestra el archivo. Generación de código, mocks e implementación son capacidades o trabajos adicionales que no se incluyen.

**¿Por qué no funciona Try it out?** Se deshabilita porque estamos revisando un acuerdo y no hay una API conectada. Los ejemplos son datos ficticios, no respuestas obtenidas de un servidor.

**¿Por qué hay varios archivos para una operación?** Cada uno tiene una función: contrato, visualización e instrucciones. La información técnica de la operación solo vive en el YAML.

**¿Cada historia tendrá su propio YAML?** No necesariamente. Una especificación puede reunir muchas operaciones y compartir esquemas. T-03, T-08 y T-11 pueden referenciar el mismo retiro sin copiarlo tres veces.

**¿Esto nos obliga a cambiar frontend o backend?** OpenAPI describe HTTP y no impone un framework. El piloto no modifica las tecnologías del README.

**¿Qué cuesta mantenerlo?** Aprender la estructura básica, revisar los cambios y verificar que contrato e implementación coincidan. Empezar con una operación permite medir ese costo antes de extenderlo.

**¿Quién aprueba?** La propuesta es una revisión conjunta de frontend, backend y QA, con reglas de negocio validadas por el responsable correspondiente. No se configura una política obligatoria de aprobaciones en este PR.

**¿Qué decisión pedimos hoy?** Validar el alcance y los campos de ATM-13, probar si la revisión resulta útil y decidir si seguimos con ATM-14. La adopción general y el CI pueden tratarse después.

## Referencias oficiales

- [OpenAPI Initiative — buenas prácticas](https://learn.openapis.org/best-practices.html)
- [OpenAPI Specification 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)
- [Swagger UI — instalación](https://swagger.io/docs/open-source-tools/swagger-ui/usage/installation/)
- [Swagger UI — configuración](https://swagger.io/docs/open-source-tools/swagger-ui/usage/configuration/)
- [Redocly CLI — lint](https://redocly.com/docs/cli/commands/lint)
- [FastAPI — OpenAPI y documentación interactiva](https://fastapi.tiangolo.com/tutorial/first-steps/)
