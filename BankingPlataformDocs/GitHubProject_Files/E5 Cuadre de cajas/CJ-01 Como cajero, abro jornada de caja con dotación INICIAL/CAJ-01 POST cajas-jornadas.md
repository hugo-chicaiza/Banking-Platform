---
number: 159
title: "CAJ-03 | POST /api/v1/caja/jornadas"
type: api
code: CAJ-01
parent: "[[CJ-01 Como cajero, abro jornada de caja con dotación INICIAL]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/159
---

`POST /api/v1/caja/jornadas` · **Roles:** CAJERO · **Historia:** CJ-01 (#51) · **OpenAPI:** `CAJ03`

Abre jornada de caja.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CajaFisica`, `Caja.CajerosAsignadosAgencia` | `Caja.JornadasCaja` | `Contabilidad.fn_IdFechaContable` |

## Reglas de negocio

1. El cajero tiene asignación vigente en la agencia de la caja → `409 CAJERO_NO_ASIGNADO_A_AGENCIA`.
2. Una jornada `ABIERTA` por cajero → `409 CAJERO_YA_TIENE_JORNADA_ABIERTA`; y por caja física → `409 CAJA_EN_USO`.
3. La caja física está activa → `409 CAJA_INACTIVA`.
4. La jornada nace `ABIERTA` con `DineroInicial`; no opera hasta registrar la dotación INICIAL (CAJ-07), que debe ser igual a ese monto (DB 51010).

## Flujo

1. Validar asignación, caja y jornadas abiertas.
2. Insertar la jornada `ABIERTA` con su fecha contable (`fn_IdFechaContable`).
3. Responder 201; el FE pasa directo a la dotación INICIAL.

## Request

Body `JornadaOpen`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCajaFisica | integer | Sí |  |
| dineroInicial | number | Sí | >= 0; debe coincidir con la dotación INICIAL |
| observacion | string(500) | No |  |

```json
{
  "idCajaFisica": 1,
  "dineroInicial": 150.0,
  "observacion": "Operación de prueba"
}
```

## Response `201`

`Jornada`

```json
{
  "idJornadaCaja": 1,
  "idUsuario": 1,
  "idCajaFisica": 1,
  "idAgencia": "001",
  "fechaHoraApertura": "2026-11-04T10:15:00-05:00",
  "fechaHoraCierre": "2026-11-04T10:15:00-05:00",
  "dineroInicial": 150.0,
  "estado": "ABIERTA",
  "observacion": "Operación de prueba"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CAJERO_YA_TIENE_JORNADA_ABIERTA` | El cajero ya tiene una jornada abierta |
| 409 | `CAJA_EN_USO` | La caja física ya tiene una jornada abierta |
| 409 | `CAJERO_NO_ASIGNADO_A_AGENCIA` | El cajero no tiene asignación vigente en la agencia de la caja |
| 409 | `CAJA_INACTIVA` | La caja física no está activa |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
