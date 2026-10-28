---
number: 192
title: "AUT-08 | PATCH /api/v1/usuarios/{idUsuario}"
type: api
code: AUT-08
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/192
---

`PATCH /api/v1/usuarios/{idUsuario}` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT08`

Edita datos o estado del usuario.

| Lee | Escribe | DB |
|---|---|---|
| — | `Organizacion.Usuarios`, `Seguridad.Bloqueos` | — |

## Reglas de negocio

1. Solo cambia `nombre`, `email` y `estado`; `username` no se edita.
2. Pasar a `Bloqueado` inserta en `Seguridad.Bloqueos` con `BloqueadoPor` del token; pasar de `Bloqueado` a `Activo` cierra el bloqueo (`FechaDesbloqueo`, `DesbloqueadoPor`) y reinicia `IntentosFallidos`.
3. Un ADMIN no puede bloquearse ni desactivarse a sí mismo → 409.
4. Email duplicado → `409 USUARIO_DUPLICADO`.

## Flujo

1. Cargar el usuario (404 si no existe).
2. Aplicar los cambios y, si cambia el estado, registrar o cerrar el bloqueo, en una transacción.
3. Responder 200 con el usuario.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idUsuario | path | integer | Sí |  |

Body `UsuarioUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| nombre | string | No |  |
| email | string | No |  |
| estado | Activo \| Inactivo \| Bloqueado | No |  |

```json
{
  "nombre": "María López",
  "email": "maria.lopez@correo.ec",
  "estado": "Activo"
}
```

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
