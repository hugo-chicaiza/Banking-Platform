# BOV-04 · Solicitudes y confirmaciones físicas

El **CAJERO** o **SUPERVISOR** registra una solicitud para una bóveda de su
agencia operativa. Un **SUPERVISOR** distinto del solicitante la aprueba o
rechaza desde la agencia de origen. La aprobación reserva el efectivo y la
capacidad para el movimiento. El inventario y la contabilidad se actualizan
al confirmar cada etapa física.

Cada agencia participante tiene un solo cupo de solicitud activa. El cupo
se ocupa al solicitar, tanto en origen como en destino, y se libera al
confirmar, devolver, rechazar, cancelar o anular. En un traslado interno,
las dos bóvedas comparten un cupo. El control de efectivo y capacidad
comienza en APROBADO. La capacidad de destino de un traslado sigue
reservada en DESPACHADO.

## API

Todas las rutas tienen prefijo **/api/v1/boveda**. Las identidades y la
agencia operativa provienen de la sesión. La API calcula los importes a
partir de los valores del catálogo y el desglose.

| Método | Ruta | Resultado |
|---|---|---|
| GET | /bovedas/{idBoveda}/destinos | Identificador, código y agencia de las bóvedas activas disponibles para solicitar un traslado |
| POST | /bovedas/{idBoveda}/solicitudes-movimiento | 201, PENDIENTE |
| GET | /solicitudes-movimiento | Página de solicitudes con filtros idAgencia, estado, page y pageSize |
| GET | /solicitudes-movimiento/{id} | Solicitud con las partes, conteos, movimientos y asientos relacionados |
| POST | /solicitudes-movimiento/{id}/aprobacion | 200, APROBADO |
| POST | /solicitudes-movimiento/{id}/despacho | 200, DESPACHADO |
| POST | /solicitudes-movimiento/{id}/recepcion | 200, RECIBIDO |
| POST | /solicitudes-movimiento/{id}/devolucion | 200, DEVUELTO |
| POST | /solicitudes-movimiento/{id}/cierre | 200, RECIBIDO |
| POST | /solicitudes-movimiento/{id}/rechazo | 200, RECHAZADA si era PENDIENTE, ANULADA si era APROBADO |
| POST | /solicitudes-movimiento/{id}/cancelacion | 200, CANCELADA por el solicitante mientras está PENDIENTE |

La creación admite Traslado, ProvisionExterna y EnvioExcedente. Para el
traslado se requiere idBovedaContraparte. Los ajustes de caja se realizan
mediante el arqueo. Las solicitudes EJECUTADA del flujo anterior se mantienen
en el historial. La ejecución directa de movimientos responde 410.

Cuando el cliente envía una **Idempotency-Key** de 1 a 64 caracteres al
crear, puede repetir la misma solicitud con el mismo usuario, clave y
datos aunque la solicitud ya se haya cerrado. La misma clave con otra
propuesta devuelve 409. Al recibir un conflicto en una confirmación,
consultar el detalle de la solicitud para recuperar su estado persistido.

### Traslados y retornos

El jefe de origen confirma el despacho con un objeto JSON. numeroGuia y
precinto se pueden incluir juntos. El despacho descuenta las denominaciones
autorizadas de origen y contabiliza el efectivo en tránsito.

El jefe de destino, distinto de quien despachó, confirma la recepción con el
desglose contado. Si difiere el importe o el desglose, debe incluir
actaNovedad. La diferencia monetaria genera un asiento adicional con cargo a
faltantes o con abono a sobrantes en tránsito. Si no llegó efectivo, el
desglose vacío registra un faltante por todo el envío. El cupo se libera al
cerrar la recepción.

En una devolución, el jefe de origen confirma la re-recepción con el
desglose y actaNovedad. RetornoRemesa crea un movimiento de ingreso y
conserva el despacho original. Una diferencia se contabiliza en el mismo
acto.

### Provisión externa y excedentes

Tras aprobar la provisión, otro supervisor de origen confirma la recepción
con el desglose físico, numeroGuia y precinto. El importe debe corresponder
a la provisión autorizada. Si cambian las denominaciones para el mismo
importe, se registra el conteo real y se exige actaNovedad. El inventario
aumenta y se contabiliza la entrada
contra banco.

El despacho de excedente requiere numeroGuia y precinto y mueve el importe
de bóveda a Remesas en Tránsito. Un supervisor de origen registra el
comprobanteBanco para liquidar la remesa hacia banco. El cierre agrega el
asiento bancario y mantiene el movimiento físico de despacho.

## Plantillas de Contabilidad

Configurar las cuentas reales de la entidad y un tipo de asiento automático
activo en Contabilidad.PlantillaBoveda. Todo asiento registra debe y haber por
el mismo importe. Los asientos de las etapas de una solicitud usan la misma
cuenta imputable de efectivo en tránsito. El sistema valida esa cuenta al
aprobar y en cada etapa que la afecta.

| Tipo y naturaleza de la plantilla | Agencia | Debe | Haber |
|---|---|---|---|
| Traslado E | Origen | Efectivo en Tránsito | Bóveda |
| Traslado I | Destino | Bóveda | Efectivo en Tránsito |
| RetornoRemesa I | Origen | Bóveda | Efectivo en Tránsito |
| FaltanteTransito E | Origen y destino | Faltante en Tránsito | Efectivo en Tránsito |
| SobranteTransito I | Origen y destino | Efectivo en Tránsito | Sobrante en Tránsito |
| ProvisionExterna I | Origen | Bóveda | Banco |
| DespachoExcedente E | Origen | Remesas en Tránsito | Bóveda |
| CierreExcedente I | Origen | Banco | Remesas en Tránsito |

Para Traslado y ProvisionExterna se reutilizan las plantillas versionadas
vigentes del módulo. Para Traslado se seleccionan en conjunto para salida
y entrada. La fuente elegida queda registrada en la aprobación. Las
plantillas de retorno, novedades en tránsito y excedentes se configuran
mediante la tabla anterior.

## SQL Server

Aplicar en CooperativaDB y en orden:
1. migrations/20261114_boveda_bov01_06.tsql.
2. migrations/20261117_boveda_solicitudes_autorizacion.tsql.
3. migrations/20261127_boveda_movimientos_confirmacion.tsql.
4. migrations/20261127_boveda_reservas_operativas.tsql.
5. migrations/20261127_boveda_arqueos_novedades.tsql.

En instalaciones parcialmente migradas, continuar desde la primera
migración pendiente. Una migración que detecte solicitudes pendientes
duplicadas para una agencia aborta con error 59020. Resolver las
solicitudes excedentes con el flujo previo y reintentar. La configuración
contable de las nuevas etapas se carga antes de habilitar las operaciones.
