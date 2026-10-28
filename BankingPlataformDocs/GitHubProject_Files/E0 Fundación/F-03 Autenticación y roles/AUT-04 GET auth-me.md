---
number: 113
title: "AUT-04 | GET /api/v1/auth/me"
type: api
code: AUT-04
parent: "[[F-03 Autenticación y roles]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/113
---

`GET /api/v1/auth/me` · **Roles:** AUTH · **Historia:** F-03 (#17) · **OpenAPI:** `AUT04`

Devuelve el usuario del token, sus roles y su agencia vigente. El FE lo usa para el menú y las rutas (F-05).

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.GruposUsuarios`, `Seguridad.Grupos`, `Caja.CajerosAsignadosAgencia` | — | SeguridadDB |

## Reglas de negocio

1. El usuario sale del token, nunca de un parámetro.
2. `roles` es lista: un usuario puede tener varios.
3. `idAgencia` = asignación vigente (`FechaFin IS NULL` y `Estado = 1`); si no hay, `null`.

## Request

Sin body ni parámetros.

## Response `200`

```json
{ "idUsuario": 12, "nombre": "María López", "roles": ["CAJERO"], "idAgencia": "001" }
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401: el FE intenta AUT-02 y, si falla, va al login.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: usuario con un rol, con varios roles y sin agencia vigente
- [ ] Disponible en el mock de F-01 para F-05
