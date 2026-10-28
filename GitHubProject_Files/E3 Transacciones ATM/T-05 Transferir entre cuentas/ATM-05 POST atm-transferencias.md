---
number: 145
title: "ATM-05 | POST /api/v1/atm/transferencias"
type: api
code: ATM-05
parent: "[[T-05 Transferir entre cuentas]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/145
---

`POST /api/v1/atm/transferencias` · **Roles:** ATM (sesión) · **Historia:** T-05 (#10) · **OpenAPI:** `ATM05`

Transferencia entre cuentas.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `Canal.*` | `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`, `Cuentas.TransaccionComision` | `Cuentas.usp_AplicarMovimientoCuenta`, `Transacciones.usp_AutorizarOperacion` |

## Reglas de negocio

1. Destino existente y `Activa` → `404 CUENTA_DESTINO_NO_ENCONTRADA`; distinto del origen → `422 CUENTA_DESTINO_IGUAL_ORIGEN`.
2. Autorización como en ATM-03 → `422 FONDOS_INSUFICIENTES` o `422 CUPO_DIARIO_EXCEDIDO`.
3. Dos transacciones relacionadas (`Transferencia_Enviada` y `Transferencia_Recibida` con `IdTransaccionRelacionada`): débito en origen y crédito en destino, en una sola transacción de DB.
4. Idempotencia por `registroUnico`.

## Flujo

1. Validar cuentas y autorizar.
2. Registrar las dos transacciones, los dos movimientos, la comisión y el asiento en una transacción.
3. Devolver el comprobante con 201.

## Request

Body `AtmTransferenciaRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuentaOrigen | integer | Sí |  |
| numeroCuentaDestino | string(20) | Sí |  |
| monto | number | Sí |  |
| registroUnico | string(12) | Sí |  |

```json
{
  "idCuentaOrigen": 1,
  "numeroCuentaDestino": "numeroCuentaDestino",
  "monto": 150.0,
  "registroUnico": "A1B2C3D4E5F6"
}
```

## Response `201`

`Comprobante`

```json
{
  "idTransaccion": 2001,
  "numeroComprobante": "COMP-001",
  "tipoTransaccion": "Transferencia",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "monto": 25.0,
  "comision": 0.0,
  "saldoDisponible": 975.0,
  "fechaHoraSistema": "2026-11-10T10:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `CUENTA_DESTINO_NO_ENCONTRADA` | La cuenta destino no existe o no está activa |
| 422 | `CUENTA_DESTINO_IGUAL_ORIGEN` | Origen y destino son la misma cuenta |
| 422 | `FONDOS_INSUFICIENTES` | El disponible no cubre monto + comisión |
| 422 | `CUPO_DIARIO_EXCEDIDO` | Supera el cupo diario del canal |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- alcance de cuentas destino, tratamiento de comisiones, reintentos y concurrencia.
