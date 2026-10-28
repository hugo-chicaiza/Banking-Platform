---
number: 215
title: "BOV-02 | GET /api/v1/boveda/bovedas/{idBoveda}"
type: api
code: BOV-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/215
---

`GET /api/v1/boveda/bovedas/{idBoveda}` · **Roles:** SUPERVISOR, CONTADOR, ADMIN · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV02`

Bóveda con saldo por denominación.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda`, `Boveda.BovedaDenominacion` | — | — |

## Reglas de negocio

1. Saldo por denominación (`BovedaDenominacion`) y totales.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |

## Response `200`

`Boveda`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
