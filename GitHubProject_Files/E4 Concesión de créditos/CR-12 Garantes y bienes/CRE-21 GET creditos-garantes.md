---
number: 95
title: "CRE-21 | GET /api/v1/creditos/garantes"
type: api
code: CRE-21
parent: "[[CR-12 Garantes y bienes]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/95
---

`GET /api/v1/creditos/garantes` · **Roles:** ASESOR · **Historia:** CR-12 (#70) · **OpenAPI:** `CRE21`

Busca garantes.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.Garante`, `Credito.GaranteBien` | — | — |

## Reglas de negocio

1. Búsqueda por identificación; incluye sus bienes.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| identificacion | query | string | No | Exacta |

## Response `200`

`array`

```json
[
  {
    "idGarante": 1,
    "idCliente": 1,
    "identificacion": "string",
    "nombres": "string",
    "apellidos": "string",
    "telefonoCelular": "string",
    "email": "string",
    "ingresoMensual": 100.0,
    "esExterno": true,
    "bienes": [
      {
        "idGaranteBien": 1,
        "tipoBien": "string",
        "descripcion": "string",
        "valorAvaluo": 100.0,
        "gravamen": "string",
        "tieneEscritura": true,
        "estado": "A"
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
