---
number: 85
title: "CRE-11 | GET /api/v1/creditos/solicitudes/{idSolicitud}/historial"
type: api
code: CRE-11
parent: "[[CR-04 Aprobación o rechazo de solicitudes]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/85
---

`GET /api/v1/creditos/solicitudes/{idSolicitud}/historial` · **Roles:** ASESOR, APROBADOR, AUDITOR · **Historia:** CR-04 (#30) · **OpenAPI:** `CRE11`

Historial de estados.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoSolicitudHistorialEstado` | — | — |

## Reglas de negocio

1. Orden cronológico; incluye usuario, fecha y observación.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idSolicitudHis": 1,
    "observacion": "string",
    "modificadoPor": 1,
    "fechaHora": "2026-11-04T10:30:00Z",
    "estadoAnterior": "string",
    "estadoNuevo": "string"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
