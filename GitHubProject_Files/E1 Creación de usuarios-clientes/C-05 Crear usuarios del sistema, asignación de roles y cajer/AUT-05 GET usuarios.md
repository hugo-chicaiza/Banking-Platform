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

Lista usuarios del sistema.

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.GruposUsuarios`, `Seguridad.Grupos` | — | — |

## Reglas de negocio

1. `q` busca por `NombreUsuario`, nombres o apellidos; `estado` filtra `Activo` | `Inactivo` | `Bloqueado`.
2. Paginado `{ items, page, pageSize, total }`, `pageSize` máx. 100.
3. Nunca devuelve `ClaveHash` ni `IntentosFallidos`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| q | query | string | No | Nombre o username |
| estado | query | string | No | Activo/Inactivo/Bloqueado |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageUsuario`

```json
{
  "items": [
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
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- Contrato dice `Seguridad.Usuario/UsuarioRol`; la DB usa `Organizacion.Usuarios` y `Seguridad.Grupos/GruposUsuarios` (SeguridadDB). Actualizar `openapi.yaml`.
