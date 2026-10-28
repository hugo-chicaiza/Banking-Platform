---
number: 119
title: "CAT-06 | GET /api/v1/catalogos/agencias"
type: api
code: CAT-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/119
---

`GET /api/v1/catalogos/agencias` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT06`

Lista las agencias con tipo, ubicación y estado.

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Agencia`, `Catalogo.Ciudad` (provincia y ciudad por `IdCiudad`) | — | — |

## Reglas de negocio

1. Devuelve todas con su `estado` (`A` activa, `I` inactiva, `C` cerrada); los formularios que crean operaciones solo ofrecen `A`.
2. Orden: `Matriz` primero, luego por `codigo`.
3. `idAgencia` (char 3) es el mismo que devuelve AUT-04.

## Request

Sin parámetros.

## Response `200`

```json
[ { "idAgencia": "001", "codigo": "MATRIZ", "nombre": "Matriz Quito", "tipoAgencia": "Matriz", "provincia": "Pichincha", "ciudad": "Quito", "estado": "A" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: orden, agencias en los tres estados, sin token

## Pendiente

- `Organizacion.Agencia` no tiene columna `Nombre` y el contrato la exige. Agregar la columna o usar `Codigo` como nombre.
