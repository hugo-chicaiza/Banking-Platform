---
number: 179
title: "BOV-04 | Solicitudes de movimiento y autorizacion independiente"
type: api
code: CAJ-21
parent: "[[CJ-09 Como supervisor, gestiono bóvedas (saldos por denomina]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/179
---

BOV-04 registra una solicitud pendiente y requiere la confirmacion personal de
otro usuario habilitado antes de ejecutar. La identidad del autorizador se obtiene
de su sesion.

## Contrato

Prefijo `/api/v1/boveda`.

| Metodo | Ruta | Resultado |
|---|---|---|
| POST | `/bovedas/{idBoveda}/solicitudes-movimiento` | Solicitud PENDIENTE |
| GET | `/solicitudes-movimiento` | Listado paginado |
| GET | `/solicitudes-movimiento/{idSolicitudMovimiento}` | Detalle y movimientos relacionados |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/aprobacion` | Ejecutar y resolver EJECUTADA |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/rechazo` | Resolver RECHAZADA con motivo |
| POST | `/solicitudes-movimiento/{idSolicitudMovimiento}/cancelacion` | Resolver CANCELADA por el solicitante |

Escrituras con `boveda:operar` (asignacion inicial SUPERVISOR). Consultas con
SUPERVISOR, CONTADOR, AUDITOR o ADMIN, respetando alcance de agencia.

La ruta anterior `POST /bovedas/{idBoveda}/movimientos` responde
410 SOLICITUD_AUTORIZACION_REQUERIDA. Los consumidores deben adoptar este contrato.

## Reglas

- Crear guarda tipo, contraparte, desglose, valores unitarios, monto, observaciones,
  solicitante y fecha. No altera efectivo ni requiere cuentas contables configuradas.
- El cuerpo no admite autorizadoPor, identidades, estado ni monto del cliente.
- Aprobar exige otro usuario, permiso, agencia de origen y solicitud pendiente.
  Se comprueban otra vez valores, existencias y configuracion contable.
- Movimientos, inventario, saldos, asientos, vinculos y estado se confirman en una
  transaccion. Un fallo conserva PENDIENTE y revierte los efectos financieros.
- Traslado crea dos movimientos ligados con el mismo desglose y solicitud.
- Rechazar y cancelar requieren motivo. No ejecutan movimientos. Las solicitudes
  resueltas conservan su contenido y decision.
- Se soporta Idempotency-Key opcional en creacion y repeticion segura de aprobacion
  por el mismo aprobador. Las aprobaciones simultaneas no duplican el movimiento.
- Los ajustes de arqueo BOV-06 y los movimientos de Caja/ATM conservan sus flujos.

## Documentacion y validacion

Detalle de request, response, errores, migracion y pruebas en
[la guia del flujo](../../../Backend/docs/BOV-04-solicitudes-autorizacion.md).
El contrato ejecutable se genera en `/api/openapi.json`.
