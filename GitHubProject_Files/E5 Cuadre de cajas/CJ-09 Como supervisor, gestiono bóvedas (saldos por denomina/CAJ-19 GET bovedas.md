---
number: 177
title: "BOV-01 | GET /api/v1/boveda/bovedas"
type: api
code: CAJ-19
parent: "[[CJ-09 Como supervisor, gestiono bóvedas (saldos por denomina]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/177
---

`GET /api/v1/boveda/bovedas` · **Roles:** SUPERVISOR, CONTADOR, ADMIN · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV01`

Lista bóvedas.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda` | — | — |

## Reglas de negocio

1. Filtros por agencia y tipo; incluye saldo actual y límites mínimo y máximo.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | query | string | No | Agencia |
| tipo | query | string | No | General/Mayor/Menor |

## Response `200`

`array`

```json
[
  {
    "idBoveda": 1,
    "codigoBoveda": "COD01",
    "tipoBoveda": "General",
    "idAgencia": "001",
    "idBovedaSuperior": 1,
    "limiteMaximo": 150.0,
    "limiteMinimo": 150.0,
    "saldoActual": 150.0,
    "estado": "A",
    "denominaciones": [
      {
        "idDenominacion": 1,
        "cantidadActual": 12
      }
    ]
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
