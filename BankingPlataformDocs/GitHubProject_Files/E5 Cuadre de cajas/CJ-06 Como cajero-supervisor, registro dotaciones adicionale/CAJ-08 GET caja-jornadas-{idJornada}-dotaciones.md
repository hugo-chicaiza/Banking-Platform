---
number: 214
title: "CAJ-08 | GET /api/v1/caja/jornadas/{idJornada}/dotaciones"
type: api
code: CAJ-08
parent: "[[CJ-06 Como cajero-supervisor, registro dotaciones adicionale]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/214
---

`GET /api/v1/caja/jornadas/{idJornada}/dotaciones` · **Roles:** CAJERO, SUPERVISOR, CONTADOR · **Historia:** CJ-06 (#56) · **OpenAPI:** `CAJ08`

Dotaciones de la jornada.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.DotacionesCaja`, `Caja.DotacionCajaDenominacion` | — | — |

## Reglas de negocio

1. Dotaciones de la jornada con su desglose, tipo y autorizador.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idDotacionCaja": 1,
    "idJornadaCaja": 1,
    "idBoveda": 1,
    "tipoDotacion": "tipoDotacion",
    "monto": 150.0,
    "idMovimientoBoveda": 1,
    "bovedaBajoMinimo": true,
    "estado": "Activo"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
