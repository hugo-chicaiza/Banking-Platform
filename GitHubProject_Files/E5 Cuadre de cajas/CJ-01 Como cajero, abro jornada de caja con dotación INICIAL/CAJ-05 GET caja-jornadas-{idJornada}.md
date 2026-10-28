---
number: 210
title: "CAJ-05 | GET /api/v1/caja/jornadas/{idJornada}"
type: api
code: CAJ-05
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/210
---

`GET /api/v1/caja/jornadas/{idJornada}` · **Roles:** CAJERO, SUPERVISOR, CONTADOR · **Historia:** CJ-01 (#51) · **OpenAPI:** `CAJ05`

Detalle de jornada.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.JornadasCaja` | — | — |

## Reglas de negocio

1. Incluye dotaciones, totales, cuadre y estado. Un cajero solo ve sus jornadas.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

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

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
