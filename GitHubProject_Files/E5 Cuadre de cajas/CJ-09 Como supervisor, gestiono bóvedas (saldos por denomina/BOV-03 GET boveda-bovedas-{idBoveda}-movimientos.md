---
number: 216
title: "BOV-03 | GET /api/v1/boveda/bovedas/{idBoveda}/movimientos"
type: api
code: BOV-03
parent: "[[CJ-09 Como supervisor, gestiono bóvedas (saldos por denomina]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/216
---

`GET /api/v1/boveda/bovedas/{idBoveda}/movimientos` · **Roles:** SUPERVISOR, CONTADOR, AUDITOR · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV03`

Movimientos de bóveda.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.MovimientoBoveda` | — | — |

## Reglas de negocio

1. Filtros por tipo y rango de fechas; paginado. Cada movimiento con naturaleza I/E y desglose.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |
| tipoMovimiento | query | string | No | Tipo |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageMovimientoBoveda`

```json
{
  "items": [
    {
      "idMovimiento": 1,
      "idBoveda": 1,
      "idBovedaContraparte": 1,
      "tipoMovimiento": "tipoMovimiento",
      "naturaleza": "I",
      "monto": 150.0,
      "saldoAnterior": 150.0,
      "saldoPosterior": 150.0,
      "autorizadoPor": 12,
      "idUsuarioMovimiento": 1,
      "idMovimientoRelacionado": 1,
      "fechaMovimiento": "2026-11-04T10:15:00-05:00"
    }
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
