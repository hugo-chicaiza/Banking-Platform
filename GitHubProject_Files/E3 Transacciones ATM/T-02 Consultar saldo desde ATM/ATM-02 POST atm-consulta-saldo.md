---
number: 141
title: "ATM-02 | POST /api/v1/atm/consulta-saldo"
type: api
code: ATM-02
parent: "[[T-02 Consultar saldo desde ATM]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/141
---

`POST /api/v1/atm/consulta-saldo` · **Roles:** ATM (sesión) · **Historia:** T-02 (#7), también T-08 · **OpenAPI:** `ATM02`

Consulta de saldo.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta` | `Transacciones.Transaccion` | `Transacciones.trg_Transaccion_Reglas`, `Transacciones.usp_AutorizarOperacion` |

## Reglas de negocio

1. La cuenta debe pertenecer a la sesión → si no, `404 CUENTA_NO_ENCONTRADA`.
2. Registra una `Transaccion` `Consulta` (`MTI 0200`, `Monto 0`) con `RegistroUnico`, STAN, RRN y código de respuesta.
3. La consulta no mueve saldo ni genera asiento (DB 53003 y 56012). Si tiene costo, se cobra con otra transacción `Cobro_Comision`.

## Flujo

1. Autorizar con `usp_AutorizarOperacion` (código 00 o 05).
2. Registrar la consulta y, si aplica, la transacción de comisión.
3. Devolver saldo disponible y contable.

## Request

Body `AtmSaldoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuenta | integer | Sí |  |
| registroUnico | string(12) | Sí | Clave de idempotencia |

```json
{
  "idCuenta": 1,
  "registroUnico": "A1B2C3D4E5F6"
}
```

## Response `200`

`Comprobante`

```json
{
  "idTransaccion": 2001,
  "numeroComprobante": "COMP-001",
  "tipoTransaccion": "Consulta",
  "estado": "Completada",
  "codigoRespuesta": "00",
  "comision": 0.0,
  "saldoDisponible": 1000.0,
  "fechaHoraSistema": "2026-11-10T10:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `CUENTA_NO_ENCONTRADA` | La cuenta no existe o no pertenece a la sesión |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- tarifa, exoneración, obligatoriedad del saldo disponible y respuesta de un reintento idempotente.
