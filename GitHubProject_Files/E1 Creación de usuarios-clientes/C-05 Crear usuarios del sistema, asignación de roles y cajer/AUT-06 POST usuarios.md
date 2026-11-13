---
number: 190
title: "AUT-06 | POST /api/v1/usuarios"
type: api
code: AUT-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/190
---

`POST /api/v1/usuarios` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT06`

Crea un usuario interno y lo invita a la organización EnquoCoop de WorkOS con su rol. La contraseña la define el usuario al aceptar la invitación: no viaja ni se guarda.

| Lee | Escribe | Externo |
|---|---|---|
| `Organizacion.Usuarios`, `Organizacion.Agencia` | `Organizacion.Usuarios`, `Auditoria.Auditoria` (CREAR) | WorkOS `send_invitation` |

## Reglas de negocio

1. `username`, `email` y `cedula` son únicos → `409 USUARIO_DUPLICADO`.
2. Un solo `rol` por usuario; va a WorkOS como `org-<rol>` (`APROBADOR_CREDITO` → `org-aprobador-credito`).
3. La agencia debe existir y estar activa (`Estado = 'A'`) → si no, `422 AGENCIA_INVALIDA`. Se guarda en `AgenciaID` (int: `"002"` → `2`).
4. Se crea `Activo`, `IntentosFallidos = 0`, `KeyUsuario = NULL` y `RolesWorkOS = rol`.
5. **Vínculo:** en su primer login (AUT-01) se guarda `KeyUsuario` buscando por email, solo si WorkOS lo verificó. Hasta entonces `vinculado = false` y la API le responde `403 USUARIO_NO_REGISTRADO`.
6. Crear un CAJERO no lo asigna a caja: eso es AUT-11.

## Flujo

1. Validar agencia, unicidad y datos.
2. Transacción: INSERT → `send_invitation(organization_id = WORKOS_ORGANIZATION_ID, role_slug)` → commit.
3. WorkOS falla → rollback y `503`. Falla el commit después de invitar → se revoca la invitación.

## Request

```json
{
  "username": "jperez",
  "nombres": "Juan",
  "apellidos": "Pérez",
  "email": "juan.perez@correo.ec",
  "cedula": "1710034065",
  "idAgencia": "002",
  "rol": "CAJERO"
}
```

`username` 3-50 (`A-Z a-z 0-9 . _ -`), `nombres`/`apellidos` ≤ 100, `email` ≤ 100 (se guarda en minúsculas), `cedula` 10 dígitos. Campos extra → 400.

## Response `201`

`UsuarioDetalle` (ver AUT-07) con `vinculado: false` y `estadoInvitacion: "pending"`.

## Errores

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `DATOS_INVALIDOS` | Formato, rol inexistente o campos extra |
| 409 | `USUARIO_DUPLICADO` | username, email o cédula ya existen |
| 422 | `AGENCIA_INVALIDA` | Agencia inexistente o inactiva |
| 422 | `WORKOS_RECHAZO` | WorkOS rechazó la invitación |
| 503 | `WORKOS_NO_DISPONIBLE` | WorkOS caído (no se crea nada) |

## Definición de terminado

- [x] Alta, duplicados, datos inválidos, agencia inactiva, WorkOS caído, falla de commit con revocación (`tests/unit/test_usuarios.py`)
- [ ] Probado contra WorkOS Staging (invitación → aceptar → `vinculado = true`)
