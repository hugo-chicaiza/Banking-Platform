---
number: 88
title: "CRE-14 | GET /api/v1/creditos/{idSolicitud}/plan"
type: api
code: CRE-14
parent: "[[CR-07 Consulta de estado de crédito y cuotas]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/88
---

`GET /api/v1/creditos/{idSolicitud}/plan` · **Roles:** ASESOR, CAJERO, SUPERVISOR · **Historia:** CR-07 (#35) · **OpenAPI:** `CRE14`

Plan de amortización vigente.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoPlanAmortizacion` | — | — |

## Reglas de negocio

1. Sin `version` devuelve el plan vigente (`EsVigente = 1`); con `version`, ese plan histórico.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |
| version | query | integer | No | Versión (default vigente) |

## Response `200`

`array`

```json
[
  {
    "numero": 1,
    "vencimiento": "2026-11-04",
    "saldoInicial": 150.0,
    "capital": 150.0,
    "interes": 150.0,
    "totalSeguros": 150.0,
    "totalImpuestos": 150.0,
    "valor": 150.0,
    "saldoFinal": 150.0
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
