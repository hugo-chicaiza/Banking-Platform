---
number: 204
title: "CAJ-01 | GET /api/v1/caja/cajas-fisicas"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/204
---

`GET /api/v1/caja/cajas-fisicas` · **Roles:** CAJERO, SUPERVISOR, ADMIN · **Historia:** CJ-01 (#51) · **OpenAPI:** `CAJ01`

Cajas físicas de la agencia.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CajaFisica` | — | — |

## Reglas de negocio

1. Lista las cajas de la agencia (por defecto la del token) con su estado y si tienen jornada abierta.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | query | string | No | Agencia |
| activa | query | boolean | No | Solo activas |

## Response `200`

`array`

```json
[
  {
    "idCajaFisica": 1,
    "idAgencia": "001",
    "codigoCaja": "COD01",
    "estado": "Activo",
    "descripcionEstado": "descripcionEstado",
    "limiteEfectivoCaja": 150.0
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
