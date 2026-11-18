# E0-10 · Mantenimiento de agencias

Rama `feat/backend-351-e010` desde `origin/develop` en `5d61688`. [Historia #351](https://github.com/hugo-chicaiza/Banking-Platform/issues/351)

## Diagnóstico y entrega por criterio

| Criterio | Estado en develop | Resultado |
| --- | --- | --- |
| 1. Alta inactiva visible | ORG-01 ya generaba el ID, pero heredaba el estado activo de SQL. Faltaba el listado administrativo. | **Completado.** El servicio crea en `I` y el listado incluye la fila. El filtro `estado` es opcional. |
| 2. Código duplicado | El repositorio ya comprobaba unicidad y traducía `UQ_Agencia_Codigo`. | **Completado.** Se conserva el 409 `CODIGO_DUPLICADO` y el índice existente. |
| 3. Operación abierta | El servicio consultaba jornadas de caja y las demás dependencias activas, con un mensaje de texto. | **Completado.** 409 `AGENCIA_CON_OPERACION` con el arreglo `bloqueos`. Se conservan las restricciones de matriz y los bloqueos operativos existentes. |
| 4. Solicitud de baja | Ambos PATCH podían desactivar directamente. | **Pendiente de E0-08.** La transición `A → I` valida primero los bloqueos. Cuando la validación pasa, responde 503 `APROBACIONES_NO_DISPONIBLES` hasta que se conecte la cola. OpenAPI describe el 202 futuro con `idSolicitud`. |
| 5. Autoaprobación | Las rutas de agencias carecían de una fase de aprobación. | **Pendiente de E0-08.** La cola debe devolver `APROBADOR_ES_SOLICITANTE`, auditar el intento y comprobar que aprueba otra persona autorizada. |
| 6. Selección e historial | CAT-06 consultaba todos los estados. | **Completado en backend.** CAT-06 ofrece solo `A` y conserva su formato. El listado administrativo y el detalle siguen incluyendo inactivas. El cambio de estado preserva los ID y las relaciones históricas. |
| 7. Acceso denegado | Las rutas existentes requerían `ADMIN`. La API ya auditaba 401 y 403 y disponía de control por sección. | **Completado con el modelo vigente.** Las cinco rutas se registraron en `organizacion.agencias` y conservan el control por rol. Un rechazo por rol usa `SIN_PERMISO` y audita `ACCESO_DENEGADO`. El editor conserva su rechazo específico `ACCESO_SECCION_RETIRADO`. |
| 8. Bitácora | El alta, la edición y el estado escribían resúmenes con detalle limitado. | **Parcial.** Alta, edición y reactivación emiten eventos estructurados con actor, roles, agencia de origen, IP, objetivo, fecha UTC, resultado e instantáneas completas de la API. El vínculo externo se representa por `vinculadaWorkos`. La persistencia usa la bitácora institucional poscommit. Si SeguridadDB falla, queda un log y faltará el detalle en la bitácora. La baja aprobada y la atribución a dos actores dependen de E0-08. |
| 9. Teclado, foco y estados de pantalla | Las rutas por sí solas no demuestran el comportamiento de la interfaz. | **Fuera del alcance de esta entrega backend.** Sin verificación visual o de teclado. |
| 10. Modo simulado del frontend | El contrato de las rutas canónicas y el 202 faltaban en OpenAPI. | **Contrato backend publicado localmente en OpenAPI.** Quedan la confirmación con frontend y la prueba de arranque en modo simulado. |

## Contrato y compatibilidad

La colección administrativa es `GET /api/v1/organizacion/agencias` y acepta `?estado=A|I|C`. La misma colección expone POST. El detalle expone GET y PATCH, y `PATCH /api/v1/organizacion/agencias/{id}/estado` conserva el formato de reactivación. Los cuatro endpoints con prefijo legado `/api/v1/agencias` apuntan a los mismos manejadores y conservan sus identificadores de operación. Los cambios intencionales son el estado inicial, la lista de selección y el tratamiento de la baja. La colección administrativa permite consultar y localizar las agencias inactivas.

Los códigos `ORG-CONSULTAR` y `ORG-AGENCIA-EDITAR` quedan como referencias de la historia. La implementación conserva la autorización instalada por rol y sección y usa el middleware de auditoría institucional. No se añadieron permisos a WorkOS.

## Integración con E0-08

El código de David está en `origin/feat/backend-349-cola-aprobaciones`. Su registro permite registrar una operación con base `cooperativa` y un manejador con `preparar`, `version` y `aplicar`. [Historia #349](https://github.com/hugo-chicaiza/Banking-Platform/issues/349)

1. Acordar el código de operación y el permiso de aprobación con David y registrarlos en la cola existente. Enrutar a esa misma operación los PATCH que hoy devuelven el 503 para una baja válida.
2. En `preparar` y al ejecutar, leer el objetivo bajo bloqueo y reutilizar `service.validar_desactivacion`. Congelar el antes, el después y el motivo en la cola. Revalidar la versión del objetivo y los bloqueos operativos al aprobar.
3. Aplicar `A → I` dentro de la transacción del manejador con la actualización condicional del repositorio. Reusar la entrega idempotente de E0-08 y registrar solicitante, aprobador e instantáneas. Resolver el PATCH legado que combina una baja con campos de edición antes de habilitarlo para que esos cambios no se escriban anticipadamente.
4. Verificar solicitud y 202, autoaprobación rechazada, aprobación desde una segunda sesión, objetivo cambiado, bloqueos que aparecen después de solicitar y recuperación tras una ejecución interrumpida.

## Datos y ensayo

La inspección de SQL Server local confirmó `IdAgencia char(3)`, el valor por defecto `A`, las restricciones de estado y tipo, `UQ_Agencia_Codigo`, `UX_Agencia_UnaMatriz` y el índice único filtrado de `KeyAgencia`. El índice de matriz abarca cualquier estado. Se conservaron esos objetos y se mantuvo `Codigo` como fuente de `nombre` de CAT-06. El alta de agencias escribe `I` explícitamente. El laboratorio inspeccionado carecía de `SeqAgenciaId`, que develop ya invocaba. La migración inicializa la secuencia después del último ID numérico si falta y su reversión solo elimina la secuencia creada por E0-10.

La bitácora inspeccionada tenía `Descripcion varchar(500)`. Se agregó `DetalleJson nvarchar(max)` para las instantáneas, con una restricción de JSON válido. La reversión se niega a eliminar el campo si ya contiene eventos.

La prueba reproducible `tests/integration/test_e010_sql_local.py` exige `E010_SQL_LOCAL=1` y usa SQL Server local con autenticación integrada. Crea una base desechable con el esquema relevante reproducido a partir del laboratorio inspeccionado y datos sintéticos. Verifica subidas y bajadas repetidas, el flujo SQL de agencias y el rechazo de una reversión que perdería la bitácora.

## Verificación

- La suite unitaria y de autorización pasó con 3671 pruebas. La integración específica de E0-10 pasó en SQL Server local.
- Ruff pasó el análisis y el control de formato. Pyright reportó cero errores. Bandit terminó correctamente con un aviso de `nosec` existente en contabilidad.
- La ejecución integral obtuvo 3857 pruebas correctas, 196 omitidas, 2 fallos y 111 errores. Las pruebas de integración afectadas intentaron usar la conexión SQL remota configurada y fallaron al conectarse. La regresión integral contra esa base queda sin verificar.
