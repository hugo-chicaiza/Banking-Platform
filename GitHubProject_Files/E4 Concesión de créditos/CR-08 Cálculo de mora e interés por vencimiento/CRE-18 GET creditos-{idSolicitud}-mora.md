---
number: 92
title: "CRE-18 | GET /api/v1/creditos/{idSolicitud}/mora"
type: api
code: CRE-18
parent: "[[CR-08 Cálculo de mora e interés por vencimiento]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/92
---

`GET /api/v1/creditos/{idSolicitud}/mora` · **Roles:** ASESOR, SUPERVISOR · **Historia:** CR-08 (#36) · **OpenAPI:** `CRE18`

Detalle de mora del crédito.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoCuotaMora` | — | — |

## Reglas de negocio

1. Por cuota vencida: capital vencido, tasa de mora, días, recargo y si está liquidada.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idMora": 1,
    "numeroCuota": 1,
    "capitalVencido": 150.0,
    "tasaMoraAnual": 0.12,
    "diasMora": 12,
    "recargoMora": 150.0,
    "fechaInicioMora": "2026-11-04",
    "fechaFinMora": "2026-11-04",
    "liquidada": true
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
