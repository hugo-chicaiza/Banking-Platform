---
number: 200
title: "CLI-12 | DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}"
type: api
code: CLI-12
parent: "[[C-07 Administración de las direcciones del cliente (alta, ed]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/200
---

`DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}` · **Roles:** ASESOR, ADMIN · **Historia:** C-07 (#57) · **OpenAPI:** `CLI12`

Baja lógica de la dirección (Estado = Eliminado).

| Lee | Escribe | DB |
|---|---|---|
| — | `Clientes.Direcciones` | — |

## Reglas de negocio

1. Baja lógica: `Estado = 'Eliminado'`.
2. La principal no se puede eliminar sin marcar otra antes → `409 NO_SE_PUEDE_ELIMINAR_PRINCIPAL`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |
| idDireccion | path | integer | Sí |  |

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `NO_SE_PUEDE_ELIMINAR_PRINCIPAL` | Es la dirección principal activa |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
