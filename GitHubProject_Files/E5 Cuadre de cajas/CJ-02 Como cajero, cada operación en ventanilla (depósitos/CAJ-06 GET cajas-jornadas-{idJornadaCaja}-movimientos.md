---
number: 164
title: "CAJ-12 | GET /api/v1/caja/jornadas/{idJornada}/movimientos"
type: api
code: CAJ-06
parent: "[[CJ-02 Como cajero, cada operación en ventanilla (depósitos]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/164
---

`GET /api/v1/caja/jornadas/{idJornada}/movimientos` · **Roles:** CAJERO, SUPERVISOR, CONTADOR · **Historia:** CJ-02 (#52) · **OpenAPI:** `CAJ12`

Movimientos de caja de la jornada.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.MovimientosCaja`, `Caja.TipoMovimientoCaja` | — | — |

## Reglas de negocio

1. Movimientos de caja de la jornada con su tipo (`TipoMovimientoCaja`) y naturaleza I/E; paginado.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageMovimientoCaja`

```json
{
  "items": [
    {
      "idMovimientoCaja": 1,
      "idTransaccion": 1,
      "idJornadaCaja": 1,
      "idTipoMovimiento": 1,
      "codigoTipoMovimiento": "COD01",
      "naturaleza": "E",
      "monto": 150.0,
      "fechaHora": "2026-11-04T10:15:00-05:00",
      "observacion": "Operación de prueba",
      "idAsientoContable": 1
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
