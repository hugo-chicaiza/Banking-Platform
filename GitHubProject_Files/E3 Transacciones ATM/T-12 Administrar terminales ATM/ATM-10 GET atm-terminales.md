---
number: 148
title: "ATM-10 | GET /api/v1/atm/terminales"
type: api
code: ATM-10
parent: "[[T-12 Administrar terminales ATM]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/148
---

`GET /api/v1/atm/terminales` · **Roles:** SUPERVISOR, ADMIN · **Historia:** T-12 (#105) · **OpenAPI:** `ATM10`

Lista terminales.

| Lee | Escribe | DB |
|---|---|---|
| `ATM.ATM` | — | — |

## Reglas de negocio

1. Filtros por agencia y estado; paginado (máx. 100).

## Flujo

1. El operador proporciona filtros y paginación.
2. Backend valida SUPERVISOR o ADMIN y limita los resultados al alcance autorizado.
3. Devuelve una página de terminales.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | query | string | No | Agencia |
| estado | query | string | No | A/I/M |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageATMTerminal`

```json
{
  "items": [
    {
      "idATM": 1,
      "codigoATM": "ATM00001",
      "tipoTerminal": "ATM",
      "idCanal": 2,
      "idAgencia": "001",
      "ubicacion": "Agencia de ejemplo",
      "estado": "A",
      "fechaInstalacion": "2026-11-10"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- valores predeterminados de paginación, campos ordenables y alcance por agencia.
