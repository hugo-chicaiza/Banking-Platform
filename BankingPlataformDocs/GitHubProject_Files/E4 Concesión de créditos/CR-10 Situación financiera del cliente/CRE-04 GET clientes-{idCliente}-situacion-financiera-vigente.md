---
number: 78
title: "CRE-04 | GET /api/v1/clientes/{idCliente}/situacion-financiera/vigente"
type: api
code: CRE-04
parent: "[[CR-10 Situación financiera del cliente]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/78
---

`GET /api/v1/clientes/{idCliente}/situacion-financiera/vigente` · **Roles:** ASESOR, APROBADOR, ADMIN · **Historia:** CR-10 (#68) · **OpenAPI:** `CRE04`

Situación financiera vigente.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.SituacionFinanciera` | — | — |

## Reglas de negocio

1. Sin situación vigente → `404 SIN_SITUACION_VIGENTE`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

## Response `200`

`SituacionFinanciera`

```json
{
  "idSituacion": 1,
  "idCliente": 1,
  "relacionLaboral": "relacionLaboral",
  "antiguedadLaboralMeses": 12,
  "ingresoMensual": 150.0,
  "gastoMensual": 150.0,
  "cuotaDeudaExterna": 150.0,
  "esVigente": true,
  "fechaDeclaracion": "2026-11-04T10:15:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `SIN_SITUACION_VIGENTE` | El cliente no tiene situación financiera vigente |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
