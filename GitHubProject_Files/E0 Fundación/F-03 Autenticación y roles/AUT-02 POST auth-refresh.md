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

`POST /api/v1/auth/refresh` · **Roles:** Cookie de sesión · **Historia:** F-03 (#17) · **OpenAPI:** `AUT02`

Renueva el access token de la sesión y reescribe la cookie `__Host-session`. Es opcional: `/me` y toda ruta protegida ya renuevan solas cuando el token vence.

| Lee | Escribe | Externo |
|---|---|---|
| Cookie `__Host-session` | Cookie `__Host-session` | WorkOS (refresh token) |

## Reglas de negocio

1. WorkOS rota el refresh token: cada uno sirve una sola vez.
2. Peticiones paralelas con la misma cookie vencida comparten una sola renovación (30 s, en memoria del proceso).
3. Si la sesión fue revocada, venció o el usuario fue bloqueado en WorkOS → `401` y se borra la cookie.
4. Exige origen permitido (CSRF): `Origin` = `FRONTEND_URL`.

## Request

Sin body. Cookie `__Host-session`.

## Response `204`

Sin contenido. `Set-Cookie: __Host-session=<nueva>`.

## Errores

Formato ProblemDetails (ver F-04).

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `NO_AUTENTICADO` | Sin cookie, o sesión inválida, revocada o vencida |
| 403 | `ORIGEN_NO_PERMITIDO` | `Origin`/`Sec-Fetch-Site` de otro sitio |

## Definición de terminado

- [x] Renovación, sin cookie, otro origen, renovación compartida y cookie vieja rechazada (`tests/unit/test_auth.py`)
