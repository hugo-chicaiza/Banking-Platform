# E0-10 · Mantenimiento de agencias

Rama `feat/backend-351-e010` rebasada sobre `origin/develop` en `f988d9b` (PR #476). El rebase reaplicó los cambios de `0058701`. [Historia #351](https://github.com/hugo-chicaiza/Banking-Platform/issues/351) · [E0-08 #349](https://github.com/hugo-chicaiza/Banking-Platform/issues/349)

## Diagnóstico y entrega por criterio

| Criterio | Estado previo | Resultado y evidencia |
| --- | --- | --- |
| 1. Alta inactiva visible | ORG-01 creaba en estado activo y faltaba el listado administrativo. | **Completado en API.** POST crea en `I`. GET administrativo devuelve activas e inactivas y admite filtro por estado. SQL local comprueba alta y listado. La pantalla actual todavía lista mediante CAT-06. |
| 2. Código duplicado | Existían la restricción única y su traducción. | **Completado.** Se conserva el 409 `CODIGO_DUPLICADO`, con evidencia SQL local. |
| 3. Operación abierta | Ya se consultaban jornadas y otras dependencias. | **Completado.** El 409 `AGENCIA_CON_OPERACION` contiene `bloqueos`. La cola repite la consulta al ejecutar, con pruebas para jornadas, cajas y bóvedas agregadas después de solicitar. |
| 4. Solicitud de baja | La etapa anterior validaba y devolvía 503 mientras faltaba E0-08. | **Completado.** Tanto el PATCH legado como el canónico devuelven 202 con `idSolicitud`, `estado: Pendiente` y `requiereAprobacion: true`. HTTP y SQL verifican que la agencia sigue activa hasta la aprobación. Un cambio intermedio invalida la solicitud incluso si se deshizo antes de aprobar. |
| 5. Autoaprobación | La cola estaba disponible en develop y faltaba registrar la operación. | **Completado.** E0-08 devuelve 403 `APROBADOR_ES_SOLICITANTE` y persiste el intento. HTTP y SQL verifican el caso propio, el mismo ID institucional con distinto sujeto, el aprobador sin permiso y el alcance fuera de agencia. Dos aprobadores concurrentes producen una sola ejecución. |
| 6. Selección e historial | CAT-06 consultaba todos los estados. | **Completado en API.** CAT-06 ofrece solo activas. El detalle y las lecturas de asignaciones conservan la agencia inactiva y sus ID. SQL local comprueba ambas vistas después de la baja. |
| 7. Acceso denegado | Las rutas administrativas usaban `ADMIN` y existía el control por sección. | **Completado.** Se preservan rol y sección, y la cola exige `agencias:aprobar` con alcance. Las rutas de agencias conservan `SIN_PERMISO` y la auditoría institucional de denegación. El editor conserva `ACCESO_SECCION_RETIRADO`. El POST genérico de aprobaciones exige usar la ruta de agencias para iniciar la baja. |
| 8. Bitácora | El registro de agencias dependía de una escritura después del commit. | **Completado en backend.** Alta, edición, reactivación y baja escriben en la bandeja existente dentro de la transacción que cambia la agencia. SQL local fuerza un fallo de escritura y verifica la reversión de las cuatro operaciones. El relevo idempotente guarda el detalle inmutable con fecha UTC, rol, agencia, sesión, origen, correlación, objetivo, resultado e instantáneas completas de API. Para la baja incluye solicitante, aprobador e ID de solicitud, incluso tras recuperación. `KeyAgencia` se representa como `vinculadaWorkos`. |
| 9. Teclado, foco y estados visuales | El flujo requiere verificación de interfaz. | **Pendiente de frontend.** |
| 10. Modo simulado | Existe OpenAPI backend. El cliente de agencias revisado espera una ficha para cualquier 2xx y usa CAT-06 como lista de mantenimiento. | **Pendiente de frontend.** Debe consumir el listado administrativo, distinguir el 202 y validar el modo simulado sin backend. |

## Contrato y dependencias

- El 200 de edición o reactivación y el 201 de alta conservan sus formas. El 202 de baja usa el DTO de E0-08 en las dos familias de rutas. Un PATCH que mezcla una baja efectiva con cambios de ficha responde 409 `BAJA_CON_EDICION`, sin aplicar cambios parciales.
- La operación `ORG-AGENCIA-EDITAR` reutiliza el catálogo y los motores de E0-08. La versión de agencia se guarda en la columna interna `Organizacion.Agencia.VersionFila` (`rowversion NOT NULL`). El ejecutor compara la versión y vuelve a consultar bloqueos bajo el bloqueo de la transacción. El comprobante de E0-08 impide aplicar dos veces, y el relevo reusa el ID de evento para evitar duplicar el registro.
- **E1-02.** Se probaron cajas físicas y bóvedas activas al aprobar. Se conservan las tablas y rutas actuales. La condición de activación por existencia de bóveda, horarios y la gestión de recursos son parte de E1-02. [Historia #361](https://github.com/hugo-chicaiza/Banking-Platform/issues/361)
- **E1-04.** Después de la baja, el repositorio rechaza la agencia como destino activo y conserva su ficha para las asignaciones previas. El bloqueo por cajero vigente sigue consultando `Caja.CajerosAsignadosAgencia`. E1-04 debe trasladar esa consulta cuando retire la tabla anterior. La migración de asignaciones y sus flujos completos quedan en esa historia. [Historia #363](https://github.com/hugo-chicaiza/Banking-Platform/issues/363)
- **Frontend revisado en solo lectura.** En la referencia local de frontend `origin/develop` (`7476261`), `AgenciasPage.tsx` usa `useAgencias()` de catálogos. `agencias.api.ts` valida el PATCH con `agenciaDetalleSchema`. El listado administrativo y la respuesta de solicitud ya están disponibles en backend. La pantalla existente necesita consumir ambos contratos antes de validar el flujo de punta a punta.
- **Auditoría institucional.** En develop, E0-08 proporciona el patrón de bandeja, detalle inmutable y relevo requerido por E0-05. Se reutilizaron esas piezas y se retiró la migración local anterior de `DetalleJson`. La auditoría de denegaciones sigue en el mecanismo institucional. Queda por probar la configuración real de identidades y permisos en un entorno autorizado. [E0-05 #347](https://github.com/hugo-chicaiza/Banking-Platform/issues/347)

## SQL local

El esquema inspeccionado ya protege el código único y la matriz única. Se conserva la secuencia de E0-10 para instalaciones que carecen de ella y se agrega la versión de concurrencia. El laboratorio usa dos bases desechables con datos sintéticos y ensaya migraciones E0-08, subida y bajada repetida de secuencia y versión, concurrencia, recuperación y relevo. La prueba requiere `E010_SQL_LOCAL=1` y corre con `tests/integration/test_e010_sql_local.py` usando SQL Server local y autenticación integrada.

La migración 1011 y el script manual se detienen si la tabla ya tiene una columna `rowversion` con otro nombre, para que se revise ese esquema antes de continuar.

## Verificación

- Ocho pruebas HTTP y SQL sobre bases desechables pasaron. Cubren solicitud pendiente, autoaprobación auditada, alcance y permiso, concurrencia, control de versión, reversión, recuperación y relevo idempotente.
- Ruff y Pyright pasaron. Bandit terminó sin hallazgos y conservó un aviso de `nosec` preexistente en contabilidad.
- La regresión unitaria y de autorización pasó con 3713 pruebas. La suite de integración que utiliza SQL remoto quedó fuera de esta verificación.
