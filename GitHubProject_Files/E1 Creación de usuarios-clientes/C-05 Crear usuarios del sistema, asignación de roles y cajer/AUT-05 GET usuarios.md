---
number: 189
title: "AUT-05 | GET /api/v1/usuarios"
type: api
code: AUT-05
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/189
---

`GET /api/v1/usuarios` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT05`

Lista los usuarios internos. Sale de la base: WorkOS no busca por nombre, no filtra por estado ni da el total.

| Lee | Escribe | Externo |
|---|---|---|
| `Organizacion.Usuarios` (SeguridadDB) | — | — |

## Reglas de negocio

1. `q` busca en username, nombres, apellidos y email (sin comodines del usuario).
2. `rol` filtra sobre `RolesWorkOS` (copia del rol de la membresía en EnquoCoop).
3. `vinculado` = tiene `KeyUsuario`: aceptó la invitación e inició sesión.
4. `sort`: `username|nombres|apellidos|email|estado|fechaCreacion` + `,asc|,desc`. Por defecto `fechaCreacion,desc`.
5. Nunca devuelve `IntentosFallidos` ni la cédula (está en AUT-07).

## Request

| Parámetro | Tipo | Regla |
|---|---|---|
| q | string | ≤ 100 |
| estado | string | `Activo` \| `Inactivo` \| `Bloqueado` |
| idAgencia | string | 3 dígitos |
| rol | string | ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR |
| vinculado | boolean | |
| page / pageSize | integer | desde 1 / ≤ 100 (20) |
| sort | string | ver regla 4 |

## Response `200`

```json
{
  "items": [
    {
      "idUsuario": 4,
      "username": "jperez",
      "nombres": "Juan",
      "apellidos": "Pérez",
      "email": "juan.perez@correo.ec",
      "rol": "CAJERO",
      "estado": "Activo",
      "idAgencia": "002",
      "vinculado": false,
      "fechaCreacion": "2026-11-08T10:00:00"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

## Errores

Formato ProblemDetails (ver F-04).

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `DATOS_INVALIDOS` / `PARAMETRO_INVALIDO` / `SORT_INVALIDO` | Parámetro inválido, desconocido o repetido |

## Definición de terminado

- [x] Paginado, filtros, parámetros inválidos (`tests/unit/test_usuarios.py`)
