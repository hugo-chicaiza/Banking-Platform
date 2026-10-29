---
number: 111
title: "AUT-02 | POST /api/v1/auth/refresh"
type: api
code: AUT-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/111
---

`POST /api/v1/auth/refresh` · **Roles:** Público · **Historia:** F-03 (#17) · **OpenAPI:** `AUT02`

Entrega un access token nuevo a partir de un refresh token válido, sin pedir la contraseña.

| Lee | Escribe | DB |
|---|---|---|
| `Seguridad.Sesiones`, `Organizacion.Usuarios`, `Seguridad.GruposUsuarios`, `Caja.CajerosAsignadosAgencia` | — | SeguridadDB |

## Reglas de negocio

1. El refresh token debe existir, no estar revocado y no estar vencido → si no, `401 TOKEN_INVALIDO`.
2. Si el usuario fue bloqueado o desactivado después del login → `401 TOKEN_INVALIDO`.
3. La respuesta tiene la misma forma que el login, con roles y agencia actualizados.

## Flujo

1. Validar el refresh token y su sesión.
2. Revalidar estado del usuario, cargar roles y agencia.
3. Generar access token y responder 200.

## Request

```json
{ "refreshToken": "<refresh-token>" }
```

## Response `200`

Igual que AUT-01 (`LoginResponse`).

## Errores

Formato ProblemDetails (ver F-04). Además de 400:

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `TOKEN_INVALIDO` | Token inexistente, revocado, vencido o usuario no activo |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] FE renueva el token automáticamente ante un 401

## Pendiente

- Decidir si cada refresh rota el token (entrega uno nuevo y revoca el anterior).
