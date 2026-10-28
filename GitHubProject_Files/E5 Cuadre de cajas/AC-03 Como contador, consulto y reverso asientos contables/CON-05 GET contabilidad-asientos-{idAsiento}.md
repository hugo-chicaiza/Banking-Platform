---
number: 208
title: "CON-05 | GET /api/v1/contabilidad/asientos/{idAsiento}"
type: api
code: CON-05
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/208
---

`GET /api/v1/contabilidad/asientos/{idAsiento}` · **Roles:** CONTADOR, AUDITOR, ADMIN · **Historia:** AC-03 (#67) · **OpenAPI:** `CON05`

Asiento con su detalle.

| Lee | Escribe | DB |
|---|---|---|
| `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables`, `Contabilidad.CuentasContables` | — | — |

## Reglas de negocio

1. Asiento con sus líneas; débitos = créditos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAsiento | path | integer | Sí |  |

## Response `200`

`Asiento`

```json
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
      "idMovimientoContable": 1,
      "idCuentaContable": 1,
      "codigoCuenta": "COD01",
      "tipoMovimiento": "DEBITO",
      "monto": 150.0,
      "idTransaccion": 1,
      "idAgencia": "001"
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
