---
number: 194
title: "AUT-10 | GET /api/v1/agencias/{idAgencia}/cajeros"
type: api
code: AUT-10
parent: "[[C-05 Crear usuarios del sistema, asignación de roles y cajer]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/194
---

`GET /api/v1/agencias/{idAgencia}/cajeros` · **Roles:** ADMIN, SUPERVISOR · **Historia:** C-05 (#48) · **OpenAPI:** `AUT10`

Cajeros asignados a la agencia (historial).

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CajerosAsignadosAgencia` | — | — |

## Reglas de negocio

1. Devuelve el historial completo de asignaciones de la agencia (vigentes y cerradas), la vigente primero.
2. Vigente = `FechaFin IS NULL` y `Estado = 1`.
3. Agencia inexistente → 404.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | path | string | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idHistorialUsuarioAgencia": 1,
    "idUsuario": 1,
    "idAgencia": "001",
    "fechaInicio": "2026-11-04T10:15:00-05:00",
    "fechaFin": "2026-11-04T10:15:00-05:00",
    "asignadoPor": 12,
    "estado": "Activo"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
