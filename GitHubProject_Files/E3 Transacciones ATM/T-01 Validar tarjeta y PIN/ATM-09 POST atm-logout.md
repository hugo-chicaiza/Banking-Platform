---
number: 140
title: "ATM-09 | POST /api/v1/atm/logout"
type: api
code: ATM-09
parent: "[[T-01 Validar tarjeta y PIN]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/140
---

`POST /api/v1/atm/logout` · **Roles:** ATM (sesión) · **Historia:** T-01 (#5) · **OpenAPI:** `ATM09`

Cierra la sesión del terminal.

| Lee | Escribe | DB |
|---|---|---|
| — | — | — |

## Reglas de negocio

1. Invalida el token de la sesión ATM; idempotente (204).

## Flujo

1. El terminal envía su sesión actual.
2. Backend cierra o invalida la sesión conforme al mecanismo acordado.
3. Devuelve 204 sin cuerpo y frontend elimina la sesión local.

## Request

Sin body ni parámetros.

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- mecanismo de revocación efectiva del token y comportamiento si la sesión ya expiró.
