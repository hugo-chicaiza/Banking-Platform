---
number: 209
title: "CON-06 | POST /api/v1/contabilidad/asientos/{idAsiento}/reverso"
type: api
code: CON-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/209
---

`POST /api/v1/contabilidad/asientos/{idAsiento}/reverso` · **Roles:** CONTADOR · **Historia:** AC-03 (#67) · **OpenAPI:** `CON06`

Reversa un asiento contabilizado.

| Lee | Escribe | DB |
|---|---|---|
| — | `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables` | `Contabilidad.trg_AsientoContable_Reglas`, `Contabilidad.usp_GenerarNumeroAsiento` |

## Reglas de negocio

1. Solo asientos `CONTABILIZADO` → `409 ASIENTO_NO_CONTABILIZADO`; ya reversado → `409 ASIENTO_YA_REVERSADO`.
2. Crea un asiento nuevo con débitos y créditos invertidos, enlazado por `IdAsientoReversion`; el original pasa a `REVERSADO`.
3. Número con `usp_GenerarNumeroAsiento` dentro de la transacción; período cerrado → 409 (DB 56007).

## Flujo

1. Validar el asiento y el período.
2. Crear el asiento inverso, enlazarlo y marcar el original en una transacción.
3. Responder 201 con el asiento de reverso.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAsiento | path | integer | Sí |  |

Body `AsientoReversoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| motivo | string | Sí |  |

```json
{
  "motivo": "Solicitud del cliente"
}
```

## Response `201`

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

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `ASIENTO_YA_REVERSADO` | El asiento ya fue reversado |
| 409 | `ASIENTO_NO_CONTABILIZADO` | El asiento no está CONTABILIZADO |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
