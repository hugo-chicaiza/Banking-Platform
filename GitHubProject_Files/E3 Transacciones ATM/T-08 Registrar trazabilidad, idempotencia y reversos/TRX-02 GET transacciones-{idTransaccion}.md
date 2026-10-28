---
number: 157
title: "TRX-02 | GET /api/v1/transacciones/{idTransaccion}"
type: api
code: TRX-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/157
---

`GET /api/v1/transacciones/{idTransaccion}` · **Roles:** SUPERVISOR, AUDITOR, CONTADOR, ADMIN · **Historia:** T-08 (#19) · **OpenAPI:** `TRX02`

Detalle de transacción (con comisiones y movimientos).

| Lee | Escribe | DB |
|---|---|---|
| `Transacciones.Transaccion`, `Transacciones.TransaccionComision`, `Cuentas.MovimientoTransaccion` | — | — |

## Reglas de negocio

1. Incluye comisiones, movimientos de cuenta y la transacción relacionada o el reverso si existe.

## Flujo

1. El usuario selecciona una transacción.
2. Backend verifica acceso y obtiene su detalle.
3. Devuelve Transaccion; la composición con comisiones y movimientos requiere acuerdo adicional.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTransaccion | path | integer | Sí |  |

## Response `200`

`Transaccion`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- composición de comisiones y movimientos; el esquema Transaccion todavía no define esas colecciones.
