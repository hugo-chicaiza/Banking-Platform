---
number: 176
title: "CAJ-11 | POST /api/v1/caja/jornadas/{idJornada}/retiros"
type: api
code: CAJ-18
parent: "[[CJ-08 Como cajero, registro un retiro en ventanilla]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/176
---

`POST /api/v1/caja/jornadas/{idJornada}/retiros` · **Roles:** CAJERO · **Historia:** CJ-08 (#61), también CJ-02 · **OpenAPI:** `CAJ11`

Retiro en ventanilla.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `Caja.JornadasCaja` | `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`, `Caja.MovimientosCaja`, `Contabilidad.*` | `Cuentas.usp_AplicarMovimientoCuenta`, `Transacciones.usp_AutorizarOperacion` |

## Reglas de negocio

1. Exige jornada `ABIERTA` → `409 JORNADA_NO_ABIERTA`.
2. Autorización con `usp_AutorizarOperacion`: fondos (51) → `422 FONDOS_INSUFICIENTES`; cuenta no activa (05) → 409.
3. La caja debe tener el efectivo (saldo teórico de la jornada) → `409 EFECTIVO_INSUFICIENTE_EN_CAJA`.
4. `Transaccion` + débito + `MovimientosCaja` (egreso) + asiento en una transacción; idempotente por `registroUnico`.

## Flujo

1. Validar jornada, efectivo de caja y autorizar.
2. Registrar transacción, débito, movimiento de caja y asiento en una transacción.
3. Responder 201 con el comprobante.

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
| 422 | `FONDOS_INSUFICIENTES` | El disponible no cubre monto + comisión |
| 409 | `EFECTIVO_INSUFICIENTE_EN_CAJA` | La caja no tiene efectivo para el retiro |
| 409 | `JORNADA_NO_ABIERTA` | La jornada no está ABIERTA |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)
