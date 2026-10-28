---
number: 158
title: "TRX-03 | POST /api/v1/transacciones/{idTransaccion}/reverso"
type: api
code: TRX-03
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/158
---

`POST /api/v1/transacciones/{idTransaccion}/reverso` · **Roles:** SUPERVISOR · **Historia:** T-08 (#19) · **OpenAPI:** `TRX03`

Reverso supervisado de una transacción.

| Lee | Escribe | DB |
|---|---|---|
| — | `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`, `Contabilidad.AsientoContable` | `Cuentas.usp_AplicarMovimientoCuenta` |

## Reglas de negocio

1. Mismas reglas que ATM-08 (DB 53002) → `409 TRANSACCION_NO_REVERSABLE` o `409 TRANSACCION_YA_REVERSADA`.
2. Si la original fue en ventanilla, su jornada debe seguir abierta → `409 JORNADA_CERRADA`.
3. `motivo` obligatorio; el supervisor sale del token.

## Flujo

1. Validar la original y la jornada.
2. Registrar reverso, movimiento contrario y asiento inverso en una transacción.
3. Responder 201 con el reverso.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTransaccion | path | integer | Sí |  |

Body `ReversoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| motivo | string | Sí |  |

```json
{
  "motivo": "Solicitud del cliente"
}
```

## Response `201`

`Transaccion`

```json
{
  "idTransaccion": 2002,
  "numeroComprobante": "COMP-REV-001",
  "registroUnico": "ATM000000005",
  "mti": "0400",
  "stan": "000005",
  "rrn": "000000000005",
  "tipoOperacion": "Reverso",
  "tipoTransaccion": "Retiro",
  "idCuenta": 501,
  "monto": 40.0,
  "codigoRespuesta": "00",
  "estado": "Completada",
  "idTransaccionRelacionada": 2001
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `TRANSACCION_YA_REVERSADA` | La transacción ya tiene reverso |
| 409 | `JORNADA_CERRADA` | La jornada ya está cerrada |
| 409 | `TRANSACCION_NO_REVERSABLE` | No es Normal, no está Completada o es de otra cuenta |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- devolución de comisiones, concurrencia y autorización del reverso según estado y jornada.
