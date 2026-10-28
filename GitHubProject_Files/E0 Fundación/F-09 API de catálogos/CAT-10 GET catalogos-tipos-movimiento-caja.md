---
number: 122
title: "CAT-10 | GET /api/v1/catalogos/tipos-movimiento-caja"
type: api
code: CAT-10
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/122
---

`GET /api/v1/catalogos/tipos-movimiento-caja` · **Roles:** AUTH · **Historia:** F-09 (#109), también CJ-02 · **OpenAPI:** `CAT10`

Lista los tipos de movimiento de caja y si son ingreso o egreso.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.TipoMovimientoCaja` | — | — |

## Reglas de negocio

1. `naturaleza`: `I` entra efectivo, `E` sale. El cuadre de caja la usa para sumar o restar.
2. `codigo` es único y es el que usa el backend; el FE muestra `descripcion`.
3. Orden: `naturaleza`, luego `codigo`.

## Request

Sin parámetros.

## Response `200`

```json
[ { "idTipoMovimientoCaja": 1, "codigo": "DEP", "descripcion": "Depósito en ventanilla", "naturaleza": "I" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, sin token
