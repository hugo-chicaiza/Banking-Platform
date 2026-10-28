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
  "idBovedaContraparte": 1,
  "autorizadoPor": 12,
  "desglose": [
    {
      "idDenominacion": 1,
      "cantidad": 12
    }
  ],
  "observaciones": "observaciones"
}
```

## Response `201`

`array`

```json
[
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

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
