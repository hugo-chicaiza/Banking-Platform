---
number: 191
title: "AUT-07 | GET /api/v1/usuarios/{idUsuario}"
type: api
code: AUT-07
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/191
---

`GET /api/v1/usuarios/{idUsuario}` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT07`

Detalle de usuario.

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.GruposUsuarios`, `Seguridad.Grupos` | — | — |

## Reglas de negocio

1. Usuario inexistente → 404.
2. Devuelve roles activos; nunca `ClaveHash`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idUsuario | path | integer | Sí |  |

## Response `200`

`Usuario`

```json
{
  "idUsuario": 1,
  "username": "mlopez",
  "nombre": "María López",
  "email": "maria.lopez@correo.ec",
  "roles": [
    "CAJERO"
  ],
  "estado": "Activo",
  "fechaCreacion": "2026-11-04T10:15:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
