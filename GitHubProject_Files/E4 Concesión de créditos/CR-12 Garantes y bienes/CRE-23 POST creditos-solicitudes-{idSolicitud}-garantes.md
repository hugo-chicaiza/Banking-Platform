---
number: 97
title: "CRE-23 | POST /api/v1/creditos/solicitudes/{idSolicitud}/garantes"
type: api
code: CRE-23
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/97
---

`POST /api/v1/creditos/solicitudes/{idSolicitud}/garantes` · **Roles:** ASESOR · **Historia:** CR-12 (#70) · **OpenAPI:** `CRE23`

Vincula un garante a la solicitud.

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.CreditoGarante` | — |

## Reglas de negocio

1. El mismo garante no se vincula dos veces → `409 GARANTE_YA_VINCULADO`; no puede ser el solicitante (DB 55002).
2. Solo en solicitudes no desembolsadas ni rechazadas.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `VincularGaranteRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idGarante | integer | Sí |  |

```json
{
  "idGarante": 1
}
```

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `GARANTE_YA_VINCULADO` | El garante ya está en la solicitud |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
