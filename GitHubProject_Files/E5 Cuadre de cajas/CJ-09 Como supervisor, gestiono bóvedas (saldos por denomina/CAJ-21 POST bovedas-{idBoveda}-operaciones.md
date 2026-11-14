---
number: 179
title: "BOV-04 | POST /api/v1/boveda/bovedas/{idBoveda}/movimientos"
type: api
code: CAJ-21
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/179
---

`POST /api/v1/boveda/bovedas/{idBoveda}/movimientos` · **Roles:** SUPERVISOR · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV04`

Traslado, ajuste o provisión externa.

| Lee | Escribe | DB |
|---|---|---|
| — | `Boveda.MovimientoBoveda`, `Boveda.MovimientoBovedaDenominacion`, `Boveda.BovedaDenominacion`, `Boveda.Boveda` | — |

## Reglas de negocio

1. Tipos: Traslado, ProvisionExterna, EnvioExcedente, AjusteFaltante, AjusteSobrante.
2. Traslado crea dos movimientos relacionados (E en origen, I en destino) con el mismo desglose → sin destino, `422 TRASLADO_REQUIERE_CONTRAPARTE`.
3. Doble custodia → `409 DOBLE_CUSTODIA_VIOLADA`; egreso sin piezas → `422 SALDO_INSUFICIENTE`.
4. Actualiza `BovedaDenominacion`, `SaldoActual` y genera asiento, en una transacción.

## Flujo

1. Validar tipo, contraparte, custodia y piezas.
2. Registrar movimientos, desglose, saldos y asiento en una transacción.
3. Responder 201 con los movimientos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |

Body `MovimientoBovedaRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoMovimiento | Traslado \| AjusteFaltante \| AjusteSobrante \| ProvisionExterna \| EnvioExcedente | Sí |  |
| idBovedaContraparte | integer | No | Obligatorio en Traslado |
| autorizadoPor | integer | Sí | Distinto del usuario que ejecuta |
| desglose | Desglose[] | Sí |  |
| observaciones | string(300) | No |  |

```json
{
  "tipoMovimiento": "Traslado",
  "idBovedaContraparte": 2,
  "autorizadoPor": 9,
  "desglose": [
    {
      "idDenominacion": 1,
      "cantidad": 2
    }
  ],
  "observaciones": "Entrega de efectivo"
}
```

## Response `201`

`array`

```json
[
  {
    "idMovimiento": 1,
    "idBoveda": 1,
    "idBovedaContraparte": 2,
    "tipoMovimiento": "Traslado",
    "naturaleza": "E",
    "monto": 40,
    "saldoAnterior": 200,
    "saldoPosterior": 160,
    "autorizadoPor": 9,
    "idUsuarioMovimiento": 7,
    "idMovimientoRelacionado": 2,
    "fechaMovimiento": "2026-11-16T10:00:00-05:00",
    "observaciones": null,
    "idAsientoContable": 1,
    "desglose": [
      {
        "idDenominacion": 1,
        "cantidad": 2
      }
    ]
  },
  {
    "idMovimiento": 2,
    "idBoveda": 2,
    "idBovedaContraparte": 1,
    "tipoMovimiento": "Traslado",
    "naturaleza": "I",
    "monto": 40,
    "saldoAnterior": 200,
    "saldoPosterior": 240,
    "autorizadoPor": 9,
    "idUsuarioMovimiento": 7,
    "idMovimientoRelacionado": 1,
    "fechaMovimiento": "2026-11-16T10:00:00-05:00",
    "observaciones": null,
    "idAsientoContable": 2,
    "desglose": [
      {
        "idDenominacion": 1,
        "cantidad": 2
      }
    ]
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `DOBLE_CUSTODIA_VIOLADA` | Quien autoriza es el mismo que opera |
| 422 | `SALDO_INSUFICIENTE` | El saldo no cubre la operación |
| 422 | `TRASLADO_REQUIERE_CONTRAPARTE` | El traslado no indica la bóveda contraparte |

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
