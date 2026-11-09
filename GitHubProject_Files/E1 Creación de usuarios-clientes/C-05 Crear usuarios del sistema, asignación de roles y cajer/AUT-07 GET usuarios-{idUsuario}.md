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

Detalle del usuario para precargar el formulario de edición.

| Lee | Escribe | Externo |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.Bloqueos` | — | WorkOS `list_invitations` (solo si no está vinculado) |

## Reglas de negocio

1. Inexistente → `404 USUARIO_NO_ENCONTRADO`.
2. `estadoInvitacion` (`pending` \| `accepted` \| `expired` \| `revoked`) solo si `vinculado = false`; si WorkOS no responde va `null` y el detalle sale igual.
3. `bloqueo`: el bloqueo abierto de `Seguridad.Bloqueos` si el usuario está `Bloqueado`.
4. Sin `IntentosFallidos`.

## Response `200` · `UsuarioDetalle`

```json
{
  "idUsuario": 4,
  "username": "jperez",
  "nombres": "Juan",
  "apellidos": "Pérez",
  "email": "juan.perez@correo.ec",
  "rol": "CAJERO",
  "estado": "Bloqueado",
  "idAgencia": "002",
  "vinculado": true,
  "fechaCreacion": "2026-11-08T10:00:00",
  "cedula": "1710034065",
  "ultimoAcceso": "2026-11-08T11:30:00",
  "estadoInvitacion": null,
  "bloqueo": { "motivo": "Fraude", "fechaBloqueo": "2026-11-08T12:00:00", "observaciones": null }
}
```

## Errores

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `USUARIO_NO_ENCONTRADO` | No existe |

## Definición de terminado

- [x] Vinculado, pendiente, WorkOS caído, inexistente (`tests/unit/test_usuarios.py`)
