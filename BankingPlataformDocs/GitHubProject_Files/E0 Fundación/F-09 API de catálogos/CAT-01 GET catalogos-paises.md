---
number: 114
title: "CAT-01 | GET /api/v1/catalogos/paises"
type: api
code: CAT-01
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/114
---

`GET /api/v1/catalogos/paises` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT01`

Lista los países para nacionalidad, residencia y direcciones.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.Paises` | — | — |

## Reglas de negocio

1. Ordenados por `nombrePais` (la tabla no tiene `Estado`).
2. `codigoPais` es ISO 3166-1 alfa-3 (`ECU`); `codigoNumerico` es el numérico de la misma norma.

## Request

Sin parámetros.

## Response `200`

```json
[
  { "codigoPais": "ECU", "codigoNumerico": "218", "nombrePais": "Ecuador" },
  { "codigoPais": "PER", "codigoNumerico": "604", "nombrePais": "Perú" }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, sin datos, sin token
