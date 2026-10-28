---
number: 89
title: "CRE-15 | GET /api/v1/creditos/{idSolicitud}/cuotas"
type: api
code: CRE-15
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/89
---

`GET /api/v1/creditos/{idSolicitud}/cuotas` · **Roles:** ASESOR, CAJERO, SUPERVISOR · **Historia:** CR-07 (#35) · **OpenAPI:** `CRE15`

Cuotas con estado, mora y total a pagar.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoCuota`, `Credito.CreditoCuotaMora`, `Credito.CreditoCuotaAbono` | — | — |

## Reglas de negocio

1. Por cuota: estado, vencimiento, capital, interés, seguros, impuestos, abonos, mora pendiente y total a pagar hoy.
2. Filtro opcional por estado (PENDIENTE, VENCIDA, PAGADA).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |
| estado | query | string | No | PENDIENTE/PAGADA/VENCIDA |

## Response `200`

`array`

```json
[
  {
    "idCuota": 1,
    "numero": 1,
    "vencimiento": "2026-11-04",
    "capitalOriginal": 150.0,
    "capitalAbonado": 150.0,
    "interes": 150.0,
    "totalSeguros": 150.0,
    "totalImpuestos": 150.0,
    "estado": "PENDIENTE",
    "diasMora": 12,
    "recargoMoraPendiente": 150.0,
    "totalAPagar": 150.0
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
