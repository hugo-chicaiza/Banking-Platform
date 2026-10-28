---
number: 211
title: "CAJ-06 | POST /api/v1/caja/jornadas/{idJornada}/cancelacion"
type: api
code: CAJ-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/211
---

`POST /api/v1/caja/jornadas/{idJornada}/cancelacion` · **Roles:** SUPERVISOR · **Historia:** CJ-01 (#51) · **OpenAPI:** `CAJ06`

Cancela una jornada sin movimientos.

| Lee | Escribe | DB |
|---|---|---|
| — | `Caja.JornadasCaja` | — |

## Reglas de negocio

1. Solo jornadas `ABIERTA` sin movimientos, dotaciones ni cuadre → `409 JORNADA_CON_MOVIMIENTOS`.
2. Pasa a `CANCELADA` (terminal) con motivo; supervisor del token.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `ReversoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| motivo | string | Sí |  |

```json
{
  "motivo": "Solicitud del cliente"
}
```

## Response `200`

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
| 409 | `JORNADA_CON_MOVIMIENTOS` | La jornada ya tiene movimientos |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
