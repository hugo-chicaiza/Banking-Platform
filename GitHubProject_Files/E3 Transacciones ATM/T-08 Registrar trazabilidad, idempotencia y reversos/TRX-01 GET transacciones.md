---
number: 156
title: "TRX-01 | GET /api/v1/transacciones"
type: api
code: TRX-01
parent: "[[T-08 Registrar trazabilidad, idempotencia y reversos]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/156
---

`GET /api/v1/transacciones` · **Roles:** SUPERVISOR, AUDITOR, CONTADOR, ADMIN · **Historia:** T-08 (#19) · **OpenAPI:** `TRX01`

Consulta de transacciones.

| Lee | Escribe | DB |
|---|---|---|
| `Transacciones.Transaccion` | — | — |

## Reglas de negocio

1. Filtros por cuenta, canal, tipo, estado y rango de fechas; paginado (máx. 100).
2. Muestra `RegistroUnico`, STAN, RRN, MTI y código de respuesta.

## Flujo

1. El usuario aplica filtros de auditoría.
2. Backend valida el rol y el alcance de datos y consulta las transacciones.
3. Devuelve una página de resultados.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | query | integer | No | Cuenta |
| tipoTransaccion | query | string | No | Tipo |
| estado | query | string | No | Estado |
| idCanal | query | integer | No | Canal |
| idAgencia | query | string | No | Agencia |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageTransaccion`

```json
{
  "items": [
    {
      "idTransaccion": 2001,
      "numeroComprobante": "COMP-001",
      "registroUnico": "ATM000000002",
      "mti": "0200",
      "stan": "000001",
      "rrn": "000000000001",
      "tipoOperacion": "Normal",
      "tipoTransaccion": "Retiro",
      "idCuenta": 501,
      "monto": 40.0,
      "codigoRespuesta": "00",
      "estado": "Completada"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- filtro o mecanismo para recuperar una operación por registroUnico ante una respuesta perdida.
