---
number: 207
title: "CON-04 | GET /api/v1/contabilidad/asientos"
type: api
code: CON-04
parent: "[[AC-03 Como contador, consulto y reverso asientos contables]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/207
---

`GET /api/v1/contabilidad/asientos` · **Roles:** CONTADOR, AUDITOR, ADMIN · **Historia:** AC-03 (#67) · **OpenAPI:** `CON04`

Consulta asientos.

| Lee | Escribe | DB |
|---|---|---|
| `Contabilidad.AsientoContable` | — | — |

## Reglas de negocio

1. Filtros por fecha, origen, agencia y estado; paginado.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| fecha | query | string | No | Fecha del asiento |
| origen | query | string | No | ATM/CAJA/CREDITO/… |
| idAgencia | query | string | No | Agencia |
| estado | query | string | No | Estado |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageAsiento`

```json
{
  "items": [
    {
      "idAsientoContable": 1,
      "numeroAsiento": "numeroAsiento",
      "fechaAsiento": "2026-11-04",
      "idTipoAsiento": 1,
      "origen": "AJUSTE",
      "concepto": "concepto",
      "totalDebito": 150.0,
      "totalCredito": 150.0,
      "estado": "BORRADOR",
      "idAsientoReversion": 1,
      "idAgencia": "001",
      "detalle": [
        {
          "idMovimientoContable": null,
          "idCuentaContable": null,
          "codigoCuenta": null,
          "tipoMovimiento": null,
          "monto": null,
          "idTransaccion": null,
          "idAgencia": null
        }
      ]
    }
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
