---
number: 202
title: "CLI-14 | GET /api/v1/clientes/{idCliente}/evaluaciones-riesgo"
type: api
code: CLI-14
parent: "[[C-08 Registro de la evaluación de riesgo LAFT, PEP y anteced]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/202
---

`GET /api/v1/clientes/{idCliente}/evaluaciones-riesgo` · **Roles:** ASESOR, SUPERVISOR, AUDITOR, ADMIN · **Historia:** C-08 (#58) · **OpenAPI:** `CLI14`

Historial de evaluaciones de riesgo.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.RiesgoCliente` | — | — |

## Reglas de negocio

1. Orden por fecha descendente; la vigente marcada con `esVigente = true`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idEvaluacion": 1,
    "idCliente": 1,
    "nivelRiesgoLAFT": "nivelRiesgoLAFT",
    "esPEP": true,
    "resultadoEvaluacion": "resultadoEvaluacion",
    "fechaEvaluacion": "2026-11-04T10:15:00-05:00",
    "evaluador": 12,
    "tieneAntecedentes": true,
    "idTipoAntecedente": 1,
    "observaciones": "observaciones"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
