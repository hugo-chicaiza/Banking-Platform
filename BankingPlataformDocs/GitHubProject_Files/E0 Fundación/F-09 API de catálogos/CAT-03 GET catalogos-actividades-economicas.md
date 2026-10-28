---
number: 116
title: "CAT-03 | GET /api/v1/catalogos/actividades-economicas"
type: api
code: CAT-03
parent: "[[F-09 API de catálogos]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/116
---

`GET /api/v1/catalogos/actividades-economicas` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT03`

Lista las actividades económicas activas para el registro de clientes (C-01) y la evaluación de crédito.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.ActividadEconomica` | — | — |

## Reglas de negocio

1. Solo `Estado = 'A'`, ordenadas por `areaActividad` y `descripcion` (el FE agrupa por área).

## Request

Sin parámetros.

## Response `200`

```json
[ { "idActividadEconomica": 4, "descripcion": "Comercio al por menor", "areaActividad": "Comercio" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, excluye inactivas, sin token
