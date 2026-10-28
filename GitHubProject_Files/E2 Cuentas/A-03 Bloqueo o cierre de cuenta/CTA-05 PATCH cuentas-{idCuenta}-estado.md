---
number: 128
title: "CTA-05 | PATCH /api/v1/cuentas/{idCuenta}/estado"
type: api
code: CTA-05
parent: "[[A-03 Bloqueo o cierre de cuenta]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/128
---

`PATCH /api/v1/cuentas/{idCuenta}/estado` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-03 (#23) · **OpenAPI:** `CTA05`

Cambia el estado (bloquear, inactivar, cerrar, reactivar).

| Lee | Escribe | DB |
|---|---|---|
| — | `Cuentas.Cuenta` | — |

## Reglas de negocio

1. Transiciones: Activa ⇄ Inactiva · Activa → Bloqueada → Activa · Activa/Inactiva → Cerrada (terminal) → si no, `409 TRANSICION_INVALIDA`.
2. Cerrar exige `Saldo = 0` y `SaldoRetenido = 0` (`CK` de la DB) → `409 CUENTA_CON_SALDO`; y sin créditos vigentes → `409 CUENTA_CON_CREDITO_VIGENTE`. Fija `FechaCierre`.
3. `motivo` obligatorio; usuario del token.
4. Bloquear la cuenta no cambia sus tarjetas, pero solo una cuenta `Activa` puede debitarse (DB 52002).

## Flujo

1. Validar la transición y las condiciones de cierre.
2. Actualizar `Estado` (y `FechaCierre`) y registrar auditoría (F-04).
3. Responder 200.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

Body `CuentaEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | Activa \| Inactiva \| Bloqueada \| Cerrada | Sí |  |
| motivo | string | Sí |  |

```json
{
  "estado": "Bloqueada",
  "motivo": "Bloqueo solicitado por el titular de la cuenta."
}
```

## Response `200`

`Cuenta`

```json
{
  "idCuenta": 1,
  "numeroCuenta": "100200300401",
  "idCliente": 1,
  "idAgencia": "001",
  "idProducto": 1,
  "tipoCuenta": "Ahorro",
  "idMoneda": 1,
  "saldo": 150.0,
  "saldoRetenido": 150.0,
  "saldoDisponible": 150.0,
  "estado": "Activa",
  "fechaApertura": "2026-11-04T10:15:00-05:00",
  "fechaUltimoMovimiento": "2026-11-04T10:15:00-05:00",
  "fechaCierre": "2026-11-04T10:15:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUENTA_CON_SALDO` | La cuenta tiene saldo o saldo retenido |
| 409 | `CUENTA_CON_CREDITO_VIGENTE` | La cuenta respalda un crédito vigente |
| 409 | `TRANSICION_INVALIDA` | El cambio de estado no está permitido |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
