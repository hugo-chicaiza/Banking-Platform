---
number: 193
title: "AUT-09 | PUT /api/v1/usuarios/{idUsuario}/roles"
type: api
code: AUT-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/193
---

`PUT /api/v1/usuarios/{idUsuario}/roles` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT09`

Reemplaza el rol del usuario. Un solo rol por usuario; vive en la membresía de WorkOS (EnquoCoop) y se copia en `RolesWorkOS`.

| Lee | Escribe | Externo |
|---|---|---|
| `Organizacion.Usuarios` | `Organizacion.Usuarios.RolesWorkOS`, `Caja.CajerosAsignadosAgencia`, `Auditoria.Auditoria` (CAMBIAR_ROL) | WorkOS (membresía o invitación) |

## Reglas de negocio

1. Vinculado o miembro de EnquoCoop → `update_organization_membership(role_slug = org-<rol>)`. Solo si el email no existe en WorkOS (invitación sin aceptar) se revoca la invitación y se envía otra con el rol nuevo. Sin `KeyUsuario` aplica la tabla de AUT-08.
2. Mismo rol → 200 sin cambios.
3. **Último ADMIN** → `409 ULTIMO_ADMIN`. Cuenta como ADMIN real: usuario `Activo`, vinculado (`KeyUsuario`) y con membresía **activa** `org-admin` en WorkOS. Una fila sin membresía no cuenta, ni una membresía con slug `admin` sin prefijo.
4. Si deja de ser CAJERO se cierra su asignación vigente de caja.
5. La sesión del usuario toma el rol nuevo cuando se renueva su access token (minutos, AUT-02).
6. WorkOS falla → la base se revierte (`503`).

## Request · `RolUpdate`

```json
{ "rol": "SUPERVISOR" }
```

## Response `200`

`UsuarioDetalle` (ver AUT-07).

## Errores

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `DATOS_INVALIDOS` | Rol inexistente o cuerpo distinto |
| 404 | `USUARIO_NO_ENCONTRADO` | No existe |
| 409 | `ULTIMO_ADMIN` | Quitaría el último ADMIN real |
| 409 | `USUARIO_WORKOS_SIN_MEMBRESIA` / `VINCULO_EN_CONFLICTO` | Ver AUT-08 |
| 422 | `WORKOS_RECHAZO` | WorkOS rechazó (el `detail` trae su código) |
| 503 | `WORKOS_NO_DISPONIBLE` | WorkOS caído (no cambia nada) |

## Definición de terminado

- [x] Vinculado, pendiente, mismo rol, rol inválido, último ADMIN, ADMIN sin membresía (`tests/unit/test_usuarios.py`)
- [x] Miembro sin `KeyUsuario` (con y sin email verificado), usuario de WorkOS sin membresía, id vinculado a otra fila
