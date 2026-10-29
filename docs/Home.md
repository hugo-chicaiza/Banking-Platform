# Documentación — Banking Platform

Punto de entrada de la documentación técnica. El README de la raíz enlaza aquí.

> **Dónde está cada cosa.** Hay dos conjuntos de documentación y conviene no
> confundirlos:
>
> | Carpeta | Qué contiene | Quién la mantiene |
> | --- | --- | --- |
> | `docs/` (esta) | Documentación **técnica**: cómo se monta, se configura y se verifica el proyecto. | Quien toca la infraestructura |
> | `GitHubProject_Files/` | El **backlog**: épicas, historias y fichas de endpoint, sincronizadas con Obsidian y con el tablero. | Quien gestiona el tablero |
>
> Una ficha de historia va en `GitHubProject_Files/`. Una guía de cómo levantar
> el entorno va aquí.

## Empezar

| Documento | Para qué |
| --- | --- |
| [Guía de instalación](06-Development/Setup-Guide.md) | Levantar backend, frontend y base de datos en tu máquina, de cero. |
| [Cómo contribuir](../CONTRIBUTING.md) | Ramas, commits, pull requests y revisión. |
| [Política de seguridad](../SECURITY.md) | Qué nunca entra al repositorio y qué hacer si algo se filtró. |

## Por área

| Documento | Para qué |
| --- | --- |
| [Frontend](../Frontend/README.md) | Estructura, comandos, entornos y controles del frontend. |
| [Puertas de calidad](08-Quality/Quality-Gates.md) | Qué verifica el CI, con qué umbrales y por qué cada uno. |
| [Protección de `main`](08-Quality/Branch-Protection.md) | Configuración exacta de la protección de rama, con los rulesets listos para importar. |

## Estado

F-02 se entrega en dos partes:

| Parte | Alcance | Estado |
| --- | --- | --- |
| **1** | CI corregido y ampliado, frontend Angular, gobernanza del repositorio, entorno local con Docker, protección de rama | Esta entrega |
| **2** | Endurecimiento del backend: validación de configuración por entorno, enmascarado de logs, identificador de traza, ProblemDetails, sondas `/health` y `/ready`, despliegue con GitHub Environments | Pendiente |

La parte 2 se construye sobre el `Backend/` que ya existe en `develop` y
adopta sus convenciones (`APP_*`, `DB_AUTH_MODE=managed_identity`,
`requirements.in`). Aportará además
`docs/07-Deployment/Environments.md`, con los cuatro entornos, sus secretos y
quién aprueba cada despliegue.

Resto de la Épica 0:

| Historia | Qué aportará a esta documentación | Estado |
| --- | --- | --- |
| F-01 (#15) | Contrato `openapi.yaml`, mock y Swagger UI | Pendiente |
| F-06 (#22) | Estrategia de pruebas, plantillas de caso y de defecto | Pendiente |
| F-07 (#107) | Datos semilla y catálogos | Pendiente |
| F-08 (#108) | Diccionario de datos y migración de brechas | Pendiente |

Los apartados que todavía no tienen documento (arquitectura de backend, de
frontend, de QA) los aportan sus historias. No se crean aquí archivos vacíos:
un documento vacío parece que existe y hace perder tiempo a quien lo abre.

## Enlaces

- [Tablero del proyecto](https://github.com/users/hugo-chicaiza/projects/4)
- [Épica 0: Fundación (#13)](https://github.com/hugo-chicaiza/Banking-Platform/issues/13)
- [Acciones del repositorio](https://github.com/hugo-chicaiza/Banking-Platform/actions)
