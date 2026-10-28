---
number: 151
title: "ATM-13 | GET /api/v1/atm/terminales/{idATM}/gavetas"
type: api
code: ATM-13
parent: "[[T-09 Abastecer ATM desde bóveda con doble custodia]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/151
---

`GET /api/v1/atm/terminales/{idATM}/gavetas` · **Roles:** SUPERVISOR, CAJERO, ADMIN · **Historia:** T-09 (#102) · **OpenAPI:** `ATM13`

Gavetas y efectivo actual por denominación.

| Lee | Escribe | DB |
|---|---|---|
| `ATM.Gaveta` | — | — |

## Reglas de negocio

1. Por gaveta: denominación, capacidad, cantidad actual y monto.

## Flujo

1. El operador selecciona un ATM autorizado.
2. Backend verifica el rol y consulta las gavetas y denominaciones asociadas.
3. Devuelve la situación actual de cada gaveta.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idATM | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idGaveta": 1,
    "numeroGaveta": 1,
    "idDenominacion": 3,
    "capacidad": 1000,
    "cantidadActual": 100,
    "estado": "A"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- alcance por agencia, significado de estados A/I y respuesta cuando el terminal exista sin gavetas. Propuesta: devolver [].
