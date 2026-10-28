---
number: 74
title: "CAT-09 | GET /api/v1/catalogos/tipos-credito"
type: api
code: CAT-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/74
---

`GET /api/v1/catalogos/tipos-credito` · **Roles:** AUTH · **Historia:** F-09 (#109), también CR-03 (#29) · **OpenAPI:** `CAT09`

Lista los tipos de crédito para la simulación (CR-03) y la solicitud (CR-01).

| Lee | Escribe | DB |
|---|---|---|
| `Credito.TipoCredito` | — | — |

## Reglas de negocio

1. Solo tipos activos, ordenados por `nombre`.
2. Las condiciones (tasa, plazo, montos) no van aquí: se piden con CRE-01.

## Request

Sin parámetros.

## Response `200`

```json
[ { "idTipoCredito": 1, "codigoTipoCredito": "CONS", "nombre": "Consumo", "descripcion": "Crédito de consumo" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, sin token
