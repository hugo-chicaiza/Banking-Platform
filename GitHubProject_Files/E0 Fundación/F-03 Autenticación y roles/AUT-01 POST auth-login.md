---
number: 110
title: "AUT-01 | GET /api/v1/auth/login + callback"
type: api
code: AUT-01
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/110
---

`GET /api/v1/auth/login` + `GET /api/v1/auth/callback` · **Roles:** Público · **Historia:** F-03 (#17) · **OpenAPI:** `AUT01`

Inicia sesión con el Hosted UI de WorkOS AuthKit (authorization code, patrón BFF). El navegador solo recibe la cookie `__Host-session`, nunca tokens.

| Lee | Escribe | Externo |
|---|---|---|
| — | `Auditoria.Auditoria` (LOGIN) | WorkOS AuthKit |

## Reglas de negocio

1. Usuarios, contraseñas, bloqueos y roles se administran en WorkOS; el backend no consulta `Organizacion.Usuarios`.
2. `return_to` solo puede ser una ruta interna (empieza con `/`, no con `//` ni `/\`); si no, se usa `/`.
3. `state` aleatorio en la cookie `__Host-oauth_state` (10 min); el callback lo compara con `compare_digest`.
4. Sesión: `__Host-session` = sesión de WorkOS cifrada con `WORKOS_COOKIE_PASSWORD`. `HttpOnly; Secure; SameSite=Lax; Path=/`, sin `Domain`, 8 h.
5. Los errores del callback no responden JSON: redirigen a `FRONTEND_URL/login?error=<code>`.

## Flujo

1. FE navega a `GET /auth/login?return_to=/clientes`.
2. Backend guarda `state` + `return_to` en cookie y responde `302` al Hosted UI.
3. AuthKit vuelve a `GET /auth/callback?code&state` (`WORKOS_REDIRECT_URI`).
4. Backend valida `state`, canjea el `code` (`authenticate_with_code` con `seal_session`), crea la cookie, audita y responde `302` a `FRONTEND_URL + return_to`.

## Errores (redirección a `/login?error=`)

| `error` | Cuándo |
|---|---|
| `LOGIN_CANCELADO` | AuthKit devuelve `error` (el usuario canceló) |
| `SOLICITUD_INVALIDA` | Falta `code`/`state` o no coincide con la cookie |
| `CREDENCIALES_INVALIDAS` | WorkOS rechaza el `code` (vencido, usado, usuario bloqueado) |
| `AUTENTICACION_NO_DISPONIBLE` | WorkOS no responde |
| `USUARIO_NO_HABILITADO` | WorkOS autenticó, pero el usuario no está vinculado y `Activo` en `Organizacion.Usuarios` (bloqueado o inactivo) o la sesión no es de EnquoCoop (membresía inactiva). No se crea la cookie y la sesión se revoca en WorkOS |

## Configuración

`WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `WORKOS_COOKIE_PASSWORD`, `WORKOS_REDIRECT_URI` (registrada en WorkOS › Redirects), `FRONTEND_URL`.

## Definición de terminado

- [x] Caso feliz, `return_to` externo, `state` inválido o ausente, cancelación, `code` rechazado y WorkOS caído (`tests/unit/test_auth.py`)
- [x] Ni tokens, ni `code`, ni cookies en logs o auditoría
- [ ] Probado contra WorkOS Staging
