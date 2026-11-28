# CAJ-07 · Dotación en dos pasos

El cajero titular puede abrir su jornada con `dineroInicial: 0`. Puede seleccionar un supervisor activo, con identidad vinculada y acceso a la agencia operativa de la jornada. El supervisor asignado debe autenticarse en esa agencia para resolver la solicitud. La confirmación vuelve a consultar la vigencia de su identidad, rol y asignación.

La solicitud registra el desglose, el monto calculado y el autorizador. El efectivo sigue disponible hasta la confirmación. Al confirmar una INICIAL, la transacción bloquea la jornada, comprueba si existe una INICIAL previa y establece `DineroInicial` para el procedimiento de Caja. Las ADICIONALES conservan ese importe. El backend calcula el saldo resultante con la misma fórmula que el cuadre, bajo el bloqueo de la jornada. Si supera `Caja.CajaFisica.LimiteEfectivoCaja`, responde `409 LIMITE_EFECTIVO_CAJA_EXCEDIDO`. Si el cuadre ya registró un saldo inicial diferente, una INICIAL devuelve `409 DOTACION_INICIAL_CUADRE_EXISTENTE`. El procedimiento institucional comprueba el saldo y las piezas disponibles de la bóveda, cuyos triggers protegen las reservas BOV-04. El backend revalida la bóveda y los valores de las denominaciones.

El asiento `DOT_CAJA` se vincula directamente con `Caja.DotacionesCaja.IdAsientoContable` y con su movimiento de bóveda. El cambio de saldo inicial, los movimientos de efectivo, el asiento y la resolución se confirman juntos. El historial CAJ-08 expone `idAsientoContable`, opcional para dotaciones anteriores.

## API

Rutas relativas a `/api/v1/caja`.

| Método | Ruta | Respuesta |
| --- | --- | --- |
| GET | `/jornadas/{idJornada}/autorizadores-dotacion` | `200` y opciones del selector |
| POST | `/jornadas/{idJornada}/solicitudes-dotacion` | `202` y solicitud |
| GET | `/jornadas/{idJornada}/solicitudes-dotacion` | `200` y hasta 100 solicitudes, con cursor opcional `antesDe` |
| POST | `/solicitudes-dotacion/{idSolicitud}/confirmacion` | `201` y dotación aplicada, o `200` para una confirmación ya aplicada |
| POST | `/solicitudes-dotacion/{idSolicitud}/rechazo` | `200` y solicitud rechazada |

Selector del cajero.

```json
[{"idUsuario":9,"nombreCompleto":"Ana Pérez"}]
```

Solicitud con la cabecera `Idempotency-Key: caja-55-inicial-01`. Al reintentar, conservar la misma clave y el mismo cuerpo. Una clave reutilizada con otros datos devuelve `409 IDEMPOTENCIA_CONFLICTO`.

```json
{
  "idBoveda": 2,
  "autorizadoPor": 9,
  "tipoDotacion": "INICIAL",
  "desglose": [{"idDenominacion": 1, "cantidad": 10}]
}
```

El servidor responde con `idSolicitud`, `autorizadoPor`, `monto` y `estado: "PENDIENTE"` entre otros campos. El supervisor asignado confirma con cuerpo vacío o `{}`. El rechazo recibe `{"motivo":"Entrega cancelada"}`. La solicitud de otra fecha contable se muestra como `CADUCADA`.

El POST directo anterior responde `410 SOLICITUD_DOTACION_REQUERIDA`. El frontend debe enviar la solicitud y actualizar los saldos y CAJ-08 cuando la confirmación se aplique. El GET de CAJ-08 sigue disponible en `/jornadas/{idJornada}/dotaciones`. En la referencia local del frontend `origin/feat/frontend-51-jornada-caja`, `AperturaJornada` ya envía `dineroInicial: 0` y el cliente consume CAJ-08. El esquema actual admite la respuesta de CAJ-08 y omite el campo nuevo `idAsientoContable` hasta incorporarlo. Esa referencia aún requiere conectar el selector y las acciones de solicitud y confirmación.

## Orden de publicación

1. Coordinar una ventana con frontend. El POST legado pasa a `410 SOLICITUD_DOTACION_REQUERIDA` cuando se despliega el backend. Revisar si hay clientes del POST directo en el ambiente de destino. El GET CAJ-08 conserva su ruta.
2. Aplicar primero `Backend/migrations/cooperativa/202611261800_caja_solicitudes_dotacion.up.sql` en CooperativaDB. En la misma sesión establecer `migration_database` con el nombre de la base de destino verificada. Confirmar que existen `Caja.SolicitudDotacion`, su índice único de INICIAL confirmada y la clave foránea de `Caja.DotacionesCaja.IdAsientoContable`. Verificar la plantilla activa `DOT_CAJA`.
3. Fusionar el cambio en `develop` después de verificar el esquema. El workflow `develop_backend-dev.yml` despliega automáticamente el backend de Dev al actualizar `develop`. Comprobar con sesiones autorizadas que el cajero puede abrir en cero, cargar el selector y enviar una solicitud y que el supervisor asignado puede confirmarla. La aplicación de esta prueba en Dev forma parte de una ventana posterior y requiere autorización.
4. Habilitar el frontend que consume el OpenAPI de CAJ-07. Mantener la misma `Idempotency-Key` al reintentar y refrescar jornada y CAJ-08 tras confirmar. Si se revierte el despliegue, conservar el esquema mientras existan solicitudes. El script `.down.sql` rechaza borrar su historial.

## Validación institucional

La suite se ejecutó en SQL Server local con la definición exacta de `Caja.usp_RegistrarDotacionCaja` extraída de Azure Dev por consulta de solo lectura. Para repetirla, apuntar `CAJ07_SQL_PROC` al archivo SQL obtenido por un operador autorizado y ejecutar `pytest tests/integration/test_caj07_doble_custodia_sql_lab.py` desde `Backend`. El laboratorio crea y elimina bases descartables en localhost.

| Casos | Resultado |
| --- | --- |
| 1 | Solicitud pendiente, reintento, conflicto de clave, confirmaciones concurrentes idempotentes y vínculo directo con el asiento. |
| 2–7 | Rechazo ante jornada cerrada, bóveda inactiva, bóveda de otra agencia, saldo insuficiente, piezas insuficientes y cambio del valor de una denominación. |
| 8 | Rollback si falla la contabilización, incluidos detalles y líneas del asiento, con reintento exitoso. |
| 9 | Rechazo de una solicitud sin aplicar efectivo. |
| 10–11 | Aperturas concurrentes con el mismo cajero o con dos cajeros en la misma caja. |
| 12 | Dos INICIALES concurrentes producen una sola confirmación. La ADICIONAL conserva `DineroInicial`. |
| 13 | Selector por agencia y revocación de la asignación antes de confirmar. |
| 14–16 | Solicitudes con autodesignación, autorizador de otra agencia o autorizador inactivo. |
| 17 | Apertura en cero y confirmación de la primera INICIAL. |
| 18 | Rechazo de una INICIAL cuando el cuadre ya fijó otro saldo inicial. |
| 19 | Límite de ventanilla con movimientos previos, incluido el monto exacto del límite. |
| 20–21 | Confirmaciones concurrentes que compiten por el límite de ventanilla o por el saldo de bóveda. |
| 22 | Reserva BOV-04 protegida por el trigger existente y rollback del intento. |
| 23 | Reaplicación de la migración, reversión con tabla vacía y protección del historial. |

Pasaron los 23 casos. Las sesiones, la auditoría y los procedimientos auxiliares del mayor se simularon en el laboratorio. Se ejecutó el motor de asientos de la aplicación con una proyección local de sus tablas. Azure Dev se consultó solo para cotejar claves, tipos, plantilla, procedimiento y restricciones. Su OpenAPI público devolvió 403. Los bundles públicos de Dev y producción no contenían llamadas al POST legado al momento de la revisión.

**Pendientes explícitos.** E1-02 para `FUERA_DE_HORARIO`, E4-06 para `DIA_CERRADO` y la prueba autenticada con el mayor contable completo en Dev.
