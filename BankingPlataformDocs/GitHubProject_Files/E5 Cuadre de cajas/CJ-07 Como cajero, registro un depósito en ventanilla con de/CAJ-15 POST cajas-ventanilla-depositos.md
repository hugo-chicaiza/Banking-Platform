---
number: 173
title: "CAJ-09 | POST /api/v1/caja/jornadas/{idJornada}/depositos"
type: api
code: CAJ-15
parent: "[[CJ-07 Como cajero, registro un depósito en ventanilla con de]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/173
---

`POST /api/v1/caja/jornadas/{idJornada}/depositos` · **Roles:** CAJERO · **Historia:** CJ-07 (#60), también CJ-02 · **OpenAPI:** `CAJ09`

Depósito en ventanilla.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `Caja.JornadasCaja`, `Canal.Canal`, `Catalogo.Denominacion` | `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`, `Caja.MovimientosCaja`, `Contabilidad.*` | `Cuentas.usp_AplicarMovimientoCuenta`, `Transacciones.trg_Transaccion_Reglas` |

## Reglas de negocio

1. Exige jornada `ABIERTA` del cajero → `409 JORNADA_NO_ABIERTA`; el canal Ventanilla exige jornada (DB 53001).
2. La cuenta destino puede recibir crédito (no `Cerrada`, DB 52002).
3. El desglose por denominación debe sumar el monto → `422 DESGLOSE_NO_COINCIDE_CON_MONTO`.
4. `Transaccion` + crédito a la cuenta + `MovimientosCaja` (ingreso) + asiento en una transacción; idempotente por `registroUnico`.
5. Si hay billetes de $50 o $100, sus series se registran después con CAJ-10.

## Flujo

1. Validar jornada, cuenta y desglose.
2. Registrar transacción, movimiento de cuenta, movimiento de caja y asiento en una transacción.
3. Responder 201 con el comprobante y si requiere series.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `OperacionVentanilla`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuenta | integer | Sí |  |
| monto | number | Sí |  |
| registroUnico | string(12) | Sí |  |
| desglose | Desglose[] | No | Obligatorio en depósitos |
| observacion | string(300) | No |  |

```json
{
  "idCuenta": 1,
  "monto": 150.0,
  "registroUnico": "A1B2C3D4E5F6",
  "desglose": [
    {
      "idDenominacion": 1,
      "cantidad": 12
    }
  ],
  "observacion": "Operación de prueba"
}
```

## Response `201`

`Comprobante`

```json
{
  "idTransaccion": 1,
  "numeroComprobante": "COMP-000123",
  "tipoTransaccion": "tipoTransaccion",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "descripcionRespuesta": "descripcionRespuesta",
  "monto": 150.0,
  "comision": 150.0,
  "saldoDisponible": 150.0,
  "denominaciones": [
    {
      "idDenominacion": 1,
      "cantidad": 12
    }
  ],
  "fechaHoraSistema": "2026-11-04T10:15:00-05:00",
  "numeroAutorizacion": "numeroAutorizacion"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `JORNADA_NO_ABIERTA` | La jornada no está ABIERTA |
| 409 | `CUENTA_NO_ACTIVA` | La cuenta no está Activa |
| 422 | `DESGLOSE_NO_COINCIDE_CON_MONTO` | La suma del desglose no es igual al monto |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)
