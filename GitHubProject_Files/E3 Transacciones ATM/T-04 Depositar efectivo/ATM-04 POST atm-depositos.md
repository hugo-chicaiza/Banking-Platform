---
number: 144
title: "ATM-04 | POST /api/v1/atm/depositos"
type: api
code: ATM-04
parent: "[[T-04 Depositar efectivo]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/144
---

`POST /api/v1/atm/depositos` · **Roles:** ATM (sesión) · **Historia:** T-04 (#9) · **OpenAPI:** `ATM04`

Depósito en ATM (P3 / decisión pendiente).

| Lee | Escribe | DB |
|---|---|---|
| — | `Transacciones.Transaccion`, `Cuentas.Cuenta`, `Cuentas.MovimientoTransaccion` | — |

## Reglas de negocio

1. No implementar: la DB no tiene casete de depósito (brecha G-08). T-04 es P3.

## Request

Body `AtmDepositoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuenta | integer | Sí |  |
| monto | number | Sí |  |
| registroUnico | string(12) | Sí |  |

```json
{
  "idCuenta": 1,
  "monto": 150.0,
  "registroUnico": "A1B2C3D4E5F6"
}
```

## Response `201`

`Comprobante`

```json
{
  "idTransaccion": 2001,
  "numeroComprobante": "COMP-001",
  "tipoTransaccion": "Deposito",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "monto": 100.0,
  "comision": 0.0,
  "saldoDisponible": 1100.0,
  "fechaHoraSistema": "2026-11-10T10:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- Decidir si el ATM acepta depósitos (G-08). Si no, cerrar T-04 y este endpoint.
