# BOV-04 — Solicitud y autorización independiente

BOV-04 registra primero una solicitud pendiente. Un segundo usuario confirma la
aprobación desde su propia sesión y ejecuta los movimientos guardados. El
autorizador se obtiene de esa sesión y queda registrado con fecha de resolución.

## Contrato y adaptación de clientes

Prefijo `/api/v1/boveda`.

| Método | Ruta | Respuesta |
|---|---|---|
| POST | `/bovedas/{idBoveda}/solicitudes-movimiento` | 201 SolicitudMovimiento |
| GET | `/solicitudes-movimiento` | 200 página de solicitudes |
| GET | `/solicitudes-movimiento/{idSolicitudMovimiento}` | 200 SolicitudMovimiento |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/aprobacion` | 201 movimientos ejecutados |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/rechazo` | 200 solicitud rechazada |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/cancelacion` | 200 solicitud cancelada |

La antigua ruta `POST /bovedas/{idBoveda}/movimientos` queda obsoleta y responde
**410 SOLICITUD_AUTORIZACION_REQUERIDA**. Este cambio exige adaptar el frontend y
los consumidores de esa operación. El resto de BOV-01..06 conserva sus rutas.

Los permisos de escritura reutilizan `boveda:operar`, asignado a SUPERVISOR y ADMIN
en la matriz inicial. Antes del despliegue debe asignarse también al rol `org-admin`
en WorkOS y renovarse la sesión: el archivo local de permisos no configura el tenant.
Las consultas admiten SUPERVISOR, CONTADOR, AUDITOR y ADMIN. Supervisor
consulta su agencia. Los roles globales pueden consultar las otras agencias.
Las escrituras exigen pertenecer a la agencia de origen, incluso para usuarios
con roles globales adicionales. No se crean roles ni permisos nuevos en WorkOS.

### Crear y revisar

```http
POST /api/v1/boveda/bovedas/1/solicitudes-movimiento
Idempotency-Key: traslado-20261117-001
Content-Type: application/json

{
  "tipoMovimiento": "Traslado",
  "idBovedaContraparte": 2,
  "desglose": [{"idDenominacion": 1, "cantidad": 50}],
  "observaciones": "Entrega acordada entre agencias"
}
```

Se conserva el tipo, origen/destino, agencia, solicitante, fecha, motivo, monto,
desglose y valores unitarios. El monto se calcula en el servidor. Identidades,
estado, monto y `autorizadoPor` enviados por el cliente se rechazan.

Crear valida bóvedas activas, alcance de agencia y denominaciones activas, sin
reservar efectivo. Las existencias y la contabilidad se validan de nuevo al
ejecutar. Crear no requiere una plantilla contable cargada ni genera asientos.
El solicitante se obtiene del usuario interno vinculado a la sesión.

`Idempotency-Key` es opcional y distingue mayúsculas, con 1..64 caracteres
`[A-Za-z0-9_-]`. El cliente debe conservarla al reintentar la creación. La misma
clave del solicitante con los mismos datos devuelve la misma solicitud, cualquiera
que sea su estado. Usarla para otros datos responde 409 IDEMPOTENCIA_CONFLICTO.
Sin clave, dos creaciones son dos solicitudes distintas.

El listado admite `idAgencia`, `estado`, `page` y `pageSize` (máximo 100), ordenado
por identificador descendente. La consulta devuelve detalle y `idsMovimientos`.
El solicitante y aprobador pueden revisar exactamente la operación guardada.
Para corregir una solicitud se cancela y se crea otra.

### Aprobar

La aprobación se envía sin cuerpo o con `{}`. Campos como monto, contraparte y
autorizador se rechazan. Solo puede aprobar otro usuario con el permiso requerido,
agencia de origen e identidad interna vigente.

Al aprobar se bloquean las bóvedas por id ascendente y luego la solicitud. Se
verifican estado pendiente, agencia, huella de datos, valores de denominación,
bóvedas activas, inventario coherente, piezas disponibles, límites numéricos,
calendario, período y plantillas contables. Los límites mínimo/máximo de bóveda
mantienen la política anterior de referencias operativas.

La transacción crea movimientos, actualiza inventario y saldo, genera los asientos,
vincula los movimientos con la solicitud y la resuelve como EJECUTADA. Un fallo
revierte toda la aprobación y conserva la solicitud PENDIENTE. `IdUsuarioMovimiento`
conserva al solicitante y `AutorizadoPor` se completa con el aprobador autenticado.
Los movimientos devueltos y BOV-03 incluyen `idSolicitudMovimiento`.

Un traslado produce dos movimientos asociados a la misma solicitud. El envío y la
recepción se registran juntos, como en el contrato anterior. Esta autorización
no incorpora una etapa de transporte o recepción física independiente.

Un reintento de aprobación por el mismo aprobador devuelve los movimientos ya
ejecutados. Otro aprobador recibe 409. El bloqueo y la unicidad por solicitud/bóveda
evitan ejecuciones duplicadas, también con peticiones simultáneas.

### Rechazar y cancelar

Ambas operaciones exigen un cuerpo como `{"motivo":"Entrega cancelada"}`.
El rechazo lo realiza otro usuario autorizado. La cancelación la realiza el
solicitante. Solo se resuelven solicitudes PENDIENTE. Se guardan actor, fecha y
motivo y se conserva el historial, sin cambios de efectivo o contabilidad.

Estados públicos y transiciones permitidas:

```text
PENDIENTE -> EJECUTADA   aprobación y ejecución atómica
PENDIENTE -> RECHAZADA  decisión de otro usuario
PENDIENTE -> CANCELADA  decisión del solicitante
```

## Migración

Aplicar `migrations/20261117_boveda_solicitudes_autorizacion.tsql` con un ejecutor
compatible con GO y que detenga errores, antes de desplegar el backend.
Requiere `20261114_boveda_bov01_06.tsql`. No se aplicó a bases de negocio durante
el desarrollo. El despliegue debe coordinarse con la adaptación del frontend.

- `Boveda.SolicitudMovimientoBoveda` guarda propuesta, identidad, estado y resolución.
- `Boveda.SolicitudMovimientoBovedaDenominacion` guarda cantidades y valores propuestos.
- `Boveda.MovimientoBoveda.IdSolicitudMovimiento` es nullable para movimientos
  históricos, Caja, ATM y ajustes de arqueos, que conservan sus propios flujos.
- FK, CHECK e índices validan relaciones, estados, fechas, montos e idempotencia.
- Un índice único evita más de un movimiento por solicitud y bóveda.
- Triggers impiden editar/borrar propuestas, detalles y resoluciones, y añadir
  detalle a solicitudes resueltas. La huella y el monto también se verifican antes
  de ejecutar.

La migración puede repetirse y no modifica saldos ni autoriza movimientos antiguos.
Las cuentas contables se configuran en PlantillaBoveda como antes.

## Errores adicionales

| HTTP | Código | Causa |
|---|---|---|
| 410 | SOLICITUD_AUTORIZACION_REQUERIDA | Uso de la antigua ejecución directa |
| 404 | SOLICITUD_MOVIMIENTO_NO_ENCONTRADA | Identificador inexistente |
| 409 | APROBADOR_IGUAL_SOLICITANTE | Autoaprobación o autorrechazo |
| 409 | SOLICITUD_MOVIMIENTO_RESUELTA | Solicitud finalizada o aprobación de otro usuario |
| 409 | SOLICITUD_MOVIMIENTO_DESACTUALIZADA | Cambio de agencia, datos o valores de referencia |
| 409 | SOLICITUD_MOVIMIENTO_INMUTABLE | Edición/borrado rechazado por la base |
| 403 | SOLO_SOLICITANTE_CANCELA | Cancelación por otro usuario |

También se conservan los errores de sesión, permisos, agencia, validación, efectivo,
calendario y contabilidad. La auditoría identifica solicitante y revisor y registra
éxitos y fallos.

## Pruebas

Se adaptaron las pruebas de movimientos para recorrer creación y aprobación.
Se añadieron pruebas HTTP de permisos, estados, identidades, inmutabilidad del
contenido, rechazo/cancelación, reintentos, disponibilidad y rollback.
El laboratorio opt-in SQL Server aplica ambas migraciones dos veces y verifica
persistencia, triggers, concurrencia y fallos posteriores a la contabilización.
Solo utiliza bases locales ficticias con nombre aleatorio y eliminación al terminar.
