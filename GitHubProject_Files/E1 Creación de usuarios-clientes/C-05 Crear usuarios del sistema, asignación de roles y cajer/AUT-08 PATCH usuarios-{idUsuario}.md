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

Edita datos, estado o agencia. `username` y `cedula` no se editan.

| Lee | Escribe | Externo |
|---|---|---|
| `Organizacion.Usuarios`, `Organizacion.Agencia` | `Organizacion.Usuarios`, `Seguridad.Bloqueos`, `Caja.CajerosAsignadosAgencia`, `Auditoria.Auditoria` (ACTUALIZAR) | WorkOS (membresía, sesiones, usuario, invitaciones) |

## Reglas de negocio

1. Omitir un campo lo conserva. Sin cambios o con campos no editables → 400.
2. **A `Bloqueado` o `Inactivo`:** desactiva la membresía en WorkOS y revoca sus sesiones vivas (no espera las 8 h). `Bloqueado` exige `motivo` (≤ 30) y abre un registro en `Seguridad.Bloqueos` (`BloqueadoPor` = admin). Si está pendiente, se revoca la invitación.
3. **A `Activo`:** reactiva la membresía; si venía de `Bloqueado`, cierra el bloqueo (`FechaDesbloqueo`, `DesbloqueadoPor`) y reinicia `IntentosFallidos`. Si está pendiente, se reenvía la invitación.
4. **Email:** vinculado → `update_user` en WorkOS; pendiente → se revoca la invitación y se envía al nuevo email. Duplicado → 409.
5. **Agencia:** actualiza `AgenciaID` (agencia activa → si no, 422). Si es CAJERO, cierra su asignación vigente y abre una en la nueva agencia.
6. Un ADMIN no se bloquea ni desactiva a sí mismo → `409 OPERACION_SOBRE_SI_MISMO`. No se desactiva al último ADMIN → `409 ULTIMO_ADMIN` (ver AUT-09).
7. WorkOS falla → la base se revierte (`503`) y lo que WorkOS ya aplicó se deshace.

## Request · `UsuarioUpdate`

```json
{ "estado": "Bloqueado", "motivo": "Fraude", "observaciones": "Caso 12" }
```

Campos: `nombres`, `apellidos`, `email`, `estado` (`Activo`\|`Inactivo`\|`Bloqueado`), `motivo` (solo al bloquear), `observaciones` (≤ 300), `idAgencia`.

## Response `200`

`UsuarioDetalle` (ver AUT-07).

## Errores

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `DATOS_INVALIDOS` | Sin cambios, campo no editable, bloqueo sin motivo |
| 404 | `USUARIO_NO_ENCONTRADO` | No existe |
| 409 | `USUARIO_DUPLICADO` / `OPERACION_SOBRE_SI_MISMO` / `ULTIMO_ADMIN` | Ver reglas |
| 422 | `AGENCIA_INVALIDA` / `WORKOS_RECHAZO` | Agencia inactiva / WorkOS rechazó |
| 503 | `WORKOS_NO_DISPONIBLE` | WorkOS caído (no cambia nada) |

## Definición de terminado

- [x] Bloqueo y desbloqueo con sesiones revocadas, email vinculado y pendiente, agencia de cajero, auto-bloqueo, último ADMIN, WorkOS caído (`tests/unit/test_usuarios.py`)
