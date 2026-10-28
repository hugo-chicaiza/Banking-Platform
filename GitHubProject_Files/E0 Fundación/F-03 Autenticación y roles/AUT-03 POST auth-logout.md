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

`POST /api/v1/auth/logout` · **Roles:** AUTH · **Historia:** F-03 (#17) · **OpenAPI:** `AUT03`

Cierra la sesión del usuario del token y revoca su refresh token.

| Lee | Escribe | DB |
|---|---|---|
| — | `Seguridad.Sesiones` (`FechaFin`, `Estado`) | SeguridadDB |

## Reglas de negocio

1. Se cierra la sesión del usuario que viene en el JWT; no lleva body.
2. Es idempotente: llamarlo dos veces responde 204.
3. El access token sigue válido hasta vencer (máx. 15 min); el FE lo borra de inmediato.

## Request

Sin body. Cabecera `Authorization: Bearer <JWT>`.

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Solo 401 (sin token válido).

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: logout, doble logout y refresh rechazado después del logout
