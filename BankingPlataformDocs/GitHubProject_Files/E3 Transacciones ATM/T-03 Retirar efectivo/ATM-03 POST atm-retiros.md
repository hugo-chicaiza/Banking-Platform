---
number: 142
title: "ATM-03 | POST /api/v1/atm/retiros"
type: api
code: ATM-03
parent: "[[T-03 Retirar efectivo]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/142
---

`POST /api/v1/atm/retiros` · **Roles:** ATM (sesión) · **Historia:** T-03 (#8), también T-08, T-11 · **OpenAPI:** `ATM03`

Retiro de efectivo.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `Canal.CanalCupoClienteCustom`, `Canal.ProductoCanalCupo`, `ATM.Gaveta`, `Transacciones.Comisiones` | `Transacciones.Transaccion`, `Transacciones.TransaccionComision`, `Cuentas.Cuenta`, `Cuentas.MovimientoTransaccion`, `ATM.Gaveta`, `ATM.GavetaMovimiento`, `Contabilidad.AsientoContable` | `Contabilidad.usp_GenerarNumeroAsiento`, `Cuentas.usp_AplicarMovimientoCuenta`, `Transacciones.fn_CalcularComision`, `Transacciones.usp_AutorizarOperacion` |

## Reglas de negocio

1. `usp_AutorizarOperacion` decide: 51 → `422 FONDOS_INSUFICIENTES`; 61 → `422 CUPO_DIARIO_EXCEDIDO` o `422 MONTO_MAX_TX_EXCEDIDO`; 65 → límite de frecuencia; 05 → `409 CUENTA_NO_ACTIVA`.
2. El monto se arma con las denominaciones de las gavetas → si no alcanza, `422 ATM_SIN_EFECTIVO` (ISO 91).
3. Idempotencia: el mismo `registroUnico` devuelve el comprobante original con 200 e `Idempotent-Replay: true`.
4. Débito (`usp_AplicarMovimientoCuenta`), comisión (`fn_CalcularComision`), descuento de gavetas (`GavetaMovimiento`) y asiento van en una sola transacción de DB.
5. Si la dispensa física falla, el terminal llama a ATM-08.

## Flujo

1. Validar sesión, cuenta e idempotencia por `registroUnico`.
2. Autorizar, armar billetes y calcular comisión.
3. En una transacción: `Transaccion`, débito, comisión, gavetas y asiento.
4. Devolver el comprobante con 201.

## Request

Body `AtmRetiroRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuenta | integer | Sí |  |
| monto | number | Sí | Múltiplo de la denominación mínima configurada |
| registroUnico | string(12) | Sí |  |
| fechaHoraDispositivo | string | No |  |

```json
{
  "idCuenta": 1,
  "monto": 150.0,
  "registroUnico": "A1B2C3D4E5F6",
  "fechaHoraDispositivo": "2026-11-04T10:15:00-05:00"
}
```

## Response `201`

`Comprobante`

```json
{
  "idTransaccion": 2001,
  "numeroComprobante": "COMP-001",
  "tipoTransaccion": "Retiro",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "monto": 40.0,
  "comision": 0.0,
  "saldoDisponible": 960.0,
  "denominaciones": [
    {
      "idDenominacion": 3,
      "cantidad": 2
    }
  ],
  "fechaHoraSistema": "2026-11-10T10:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `FONDOS_INSUFICIENTES` | El disponible no cubre monto + comisión (código 51) |
| 422 | `CUPO_DIARIO_EXCEDIDO` | Supera el cupo diario del canal (código 61) |
| 422 | `MONTO_MAX_TX_EXCEDIDO` | Supera el máximo por transacción del canal |
| 422 | `ATM_SIN_EFECTIVO` | Las gavetas no pueden armar el monto (código 91) |
| 409 | `CUENTA_NO_ACTIVA` | La cuenta no está Activa |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- Quién puede exonerar comisiones (T-11): nunca desde la sesión ATM.
