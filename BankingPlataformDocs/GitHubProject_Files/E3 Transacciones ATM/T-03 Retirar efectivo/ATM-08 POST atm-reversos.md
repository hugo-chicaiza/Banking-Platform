---
number: 143
title: "ATM-08 | POST /api/v1/atm/reversos"
type: api
code: ATM-08
parent: "[[T-03 Retirar efectivo]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/143
---

`POST /api/v1/atm/reversos` · **Roles:** ATM (sesión) · **Historia:** T-03 (#8), también T-08 · **OpenAPI:** `ATM08`

Reverso iniciado por el terminal (MTI 0400).

| Lee | Escribe | DB |
|---|---|---|
| `Transacciones.Transaccion` | `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `ATM.GavetaMovimiento` | `Cuentas.usp_AplicarMovimientoCuenta`, `Transacciones.trg_Transaccion_Reglas` |

## Reglas de negocio

1. Solo se reversa una transacción `Normal`, `Completada` y de la misma cuenta (DB 53002) → `409 TRANSACCION_NO_REVERSABLE`; ya reversada → `409 TRANSACCION_YA_REVERSADA`.
2. Crea una `Transaccion` `Reverso` (`MTI 0400`) ligada a la original, acredita la cuenta, devuelve los billetes a las gavetas y reversa el asiento, en una transacción.
3. La original pasa a `Reversada`. Idempotente por `registroUnico` del reverso.

## Flujo

1. Ubicar la original y validar que se puede reversar.
2. Registrar reverso, movimiento, gavetas y asiento en una transacción.
3. Devolver el comprobante del reverso.

## Request

Body `AtmReversoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idTransaccion | integer | Sí |  |
| motivo | FALLA_DISPENSADOR \| TIMEOUT \| CLIENTE_NO_RETIRO_EFECTIVO \| OTRO | Sí |  |

```json
{
  "idTransaccion": 1,
  "motivo": "FALLA_DISPENSADOR"
}
```

## Response `201`

`Comprobante`

```json
{
  "idTransaccion": 2002,
  "numeroComprobante": "COMP-REV-001",
  "tipoTransaccion": "Reverso",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "monto": 40.0,
  "comision": 0.0,
  "fechaHoraSistema": "2026-11-10T10:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `TRANSACCION_YA_REVERSADA` | La transacción ya tiene reverso |
| 409 | `TRANSACCION_NO_REVERSABLE` | No es Normal, no está Completada o es de otra cuenta |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- plazo y causas válidas para reversar, devolución de comisiones y tratamiento de entrega parcial de efectivo.
