---
number: 91
title: "CRE-17 | POST /api/v1/creditos/{idSolicitud}/pagos"
type: api
code: CRE-17
parent: "[[CR-06 Registro de pago de cuota]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/91
---

`POST /api/v1/creditos/{idSolicitud}/pagos` · **Roles:** CAJERO · **Historia:** CR-06 (#34), también CR-09, CJ-02 · **OpenAPI:** `CRE17`

Registra el pago de una cuota.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoCuota`, `Credito.CreditoCuotaMora`, `Caja.JornadasCaja` | `Credito.CreditoCuotaPago`, `Credito.CreditoCuotaAbono`, `Credito.CreditoCuota`, `Credito.CreditoCuotaMora`, `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Caja.MovimientosCaja`, `Contabilidad.*` | `Credito.trg_CreditoCuotaPago_Estado`, `Cuentas.usp_AplicarMovimientoCuenta` |

## Reglas de negocio

1. En ventanilla exige jornada `ABIERTA` del cajero → `409 SIN_JORNADA_ABIERTA` (canal Ventanilla con `RequiereJornadaCaja`).
2. Se paga en orden: con cuotas anteriores pendientes → `409 CUOTAS_ANTERIORES_PENDIENTES`; cuota ya pagada → `409 CUOTA_YA_PAGADA`.
3. El pago liquida primero la mora (`Liquidada = 1`). Si cubre la cuota se crea `CreditoCuotaPago` y la cuota pasa a `PAGADA` (DB 55004); si no, se registra `CreditoCuotaAbono`.
4. `Transaccion` `Pago_Credito` con la cuenta del cliente (brecha G-10), movimiento de caja, asiento e idempotencia por `registroUnico`, todo en una transacción.

## Flujo

1. Validar jornada, cuota y orden; cotizar como CRE-16.
2. Registrar transacción, pago o abono, mora liquidada, movimiento de caja y asiento en una transacción.
3. Responder 201 con el comprobante.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `PagoCuotaRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| numeroCuota | integer | Sí |  |
| monto | number | Sí | Debe cubrir el total a pagar de la cuota (pago parcial: abono a capital) |
| registroUnico | string(12) | Sí |  |
| idJornadaCaja | integer | No | Obligatorio en canal ventanilla |
| idCuenta | integer | Sí | Cuenta del cliente asociada a la transacción |
| esCancelacionAnticipada | boolean | No |  |

```json
{
  "numeroCuota": 1,
  "monto": 100.0,
  "registroUnico": "string",
  "idJornadaCaja": 1,
  "idCuenta": 1,
  "esCancelacionAnticipada": true
}
```

## Response `201`

`PagoCuota`

```json
{
  "idCreditoCuotaPago": 1,
  "idTransaccion": 1,
  "numeroComprobante": "COMP-000123",
  "numeroCuota": 1,
  "capital": 150.0,
  "interes": 150.0,
  "totalSeguros": 150.0,
  "totalImpuestos": 150.0,
  "recargoMora": 150.0,
  "totalPagado": 150.0,
  "diasMora": 12,
  "fechaPago": "2026-11-04",
  "estadoCuota": "estadoCuota"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUOTA_YA_PAGADA` | La cuota ya está PAGADA |
| 409 | `JORNADA_NO_ABIERTA` | La jornada no está ABIERTA |
| 422 | `MONTO_INSUFICIENTE` | El monto no cubre lo exigido |
| 409 | `CUOTAS_ANTERIORES_PENDIENTES` | Hay cuotas anteriores sin pagar |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)
