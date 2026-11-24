# Contrato de edición de usuarios E1-04

Las rutas están bajo `/api/v1/usuarios`. Un `200` de edición, traslado o sustitución directa de roles contiene `UsuarioDetalle`. Actualice la ficha, el listado y el historial o contexto de agencia según el cambio. El backend mantiene la autorización y valida el alcance.

## Roles

`PUT /usuarios/{idUsuario}/roles` acepta `{"roles":["CAJERO"]}`. El campo anterior `rol` sigue disponible para perfiles de un solo rol. Un `202` devuelve `{"idSolicitud":123,"estado":"Pendiente","requiereAprobacion":true}`. Muestre la solicitud pendiente y consulte su estado en Aprobaciones. Actualice el detalle del usuario cuando la solicitud llegue a `Ejecutada`. Si la aprobación devuelve `503 APROBACION_PENDIENTE_RECUPERACION`, conserve el ID y consulte la misma solicitud. Los estados `Rechazada` y `Cancelada` cierran la solicitud sin aplicar el cambio.

## Correo

Envíe `PATCH /usuarios/{idUsuario}` con solo `{"email":"nuevo@example.test"}` cuando esté habilitada la recuperación persistente. En cuentas vinculadas, el `200` se devuelve tras confirmar el correo en WorkOS y guardar SQL. Ante un `503`, consulte la ficha y espere si el backend sigue indicando conciliación. El alta o la edición de una invitación pueden enviar un correo al destinatario. Evite reenviar automáticamente una petición que terminó con resultado incierto.

## Errores

| HTTP | Código | Comportamiento del cliente |
|---|---|---|
| 403 | `AUTOGESTION_NO_PERMITIDA`, `APROBADOR_ES_SOLICITANTE`, `SIN_PERMISO` | Muestre el rechazo y conserve el estado confirmado. |
| 409 | `USUARIO_CON_JORNADA_ABIERTA`, `CAJERO_CON_JORNADA_ABIERTA`, `ULTIMO_ADMIN` | Muestre el motivo. |
| 409 | `USUARIO_EN_CONCILIACION` | Espere a que concluya la conciliación antes de enviar otro cambio. |
| 409 | `ASIGNACIONES_CAJA_OCUPADAS` | Recargue el recurso y permita reintentar tras el cambio concurrente. |
| 409 | `APROBACION_REQUERIDA`, `CORTE_CAJA_PENDIENTE`, `USUARIO_PENDIENTE_DE_VINCULO` | Explique qué precondición falta. |
| 422 | `NIVEL_INSUFICIENTE`, `ROLES_INCOMPATIBLES` | Mantenga el borrador y muestre la restricción. |
| 422 | `CORREO_REQUIERE_CAMBIO_SEPARADO` | Envíe el cambio de correo por separado. |
| 503 | `POLITICA_ROLES_NO_CONFIGURADA`, `OPERACION_NO_CONFIGURADA` | Muestre indisponibilidad de configuración. |
| 503 | `CORREO_EN_CONCILIACION`, `ROLES_PENDIENTES_CONFIRMACION`, `WORKOS_NO_DISPONIBLE` | Consulte el estado confirmado antes de reintentar. |

La conciliación de invitaciones bloquea su vínculo mientras haya evidencia ambigua. El SDK no expone el rol de una invitación ni una clave de idempotencia para su envío. El backend conserva el incidente cuando no puede verificar la invitación anterior como única y vigente. La resolución requiere revisión operativa.
