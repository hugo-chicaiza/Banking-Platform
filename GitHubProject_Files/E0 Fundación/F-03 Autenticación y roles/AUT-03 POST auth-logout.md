---
number: 112
title: "AUT-03 | POST /api/v1/auth/logout"
type: api
code: AUT-03
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/112
---

`POST /api/v1/auth/logout` · **Roles:** Cookie de sesión · **Historia:** F-03 (#17) · **OpenAPI:** `AUT03`

Borra la cookie de sesión y devuelve la URL de WorkOS que cierra la sesión del Hosted UI.

| Lee | Escribe | Externo |
|---|---|---|
| Cookie `__Host-session` | `Auditoria.Auditoria` (LOGOUT) | WorkOS (`get_logout_url`) |

## Reglas de negocio

1. El FE debe navegar a `logoutUrl`: si no, AuthKit mantiene su sesión y el próximo login entra sin pedir credenciales.
2. `logoutUrl` vuelve a `FRONTEND_URL/login` (registrar en WorkOS › Sign-out redirect).
3. Idempotente: sin sesión o con sesión inválida responde `200` con `logoutUrl = FRONTEND_URL/login`.
4. Si el access token venció se renueva primero para obtener el id de la sesión.
5. Exige origen permitido (CSRF).

## Request

Sin body. Cookie `__Host-session`.

## Response `200`

```json
{ "logoutUrl": "https://api.workos.com/user_management/sessions/logout?session_id=...&return_to=..." }
```

`Set-Cookie: __Host-session=; Max-Age=0`.

## Errores

Formato ProblemDetails (ver F-04). Solo `403 ORIGEN_NO_PERMITIDO`.

## Definición de terminado

- [x] Logout, token vencido, sin sesión (doble logout) y otro sitio (`tests/unit/test_auth.py`)
