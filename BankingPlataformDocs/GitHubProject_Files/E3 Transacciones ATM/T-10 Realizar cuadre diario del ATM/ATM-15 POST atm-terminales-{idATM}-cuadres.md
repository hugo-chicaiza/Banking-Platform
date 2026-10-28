---
number: 153
title: "ATM-15 | POST /api/v1/atm/terminales/{idATM}/cuadres"
type: api
code: ATM-15
parent: "[[T-10 Realizar cuadre diario del ATM]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/153
---

`POST /api/v1/atm/terminales/{idATM}/cuadres` · **Roles:** SUPERVISOR · **Historia:** T-10 (#103) · **OpenAPI:** `ATM15`

Genera el cuadre del día (saldos teóricos).

| Lee | Escribe | DB |
|---|---|---|
| `Transacciones.Transaccion`, `ATM.GavetaMovimiento` | `ATM.CuadreATM` | — |

## Reglas de negocio

1. Uno por ATM y fecha contable (`UQ_CuadreATM_ATM_FechaContable`) → `409 CUADRE_YA_EXISTE`.
2. Calcula `SaldoFinalTeorico = SaldoInicial + abastecimientos - retiros` desde las transacciones y `GavetaMovimiento`.
3. Nace en `PENDIENTE_ARQUEO`.

## Flujo

1. SUPERVISOR selecciona ATM y fecha contable y presenta saldoInicial.
2. Backend valida el saldo inicial y la ausencia de otro cuadre para ese ATM y fecha.
3. Calcula los saldos teóricos, crea el cuadre y lo devuelve.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idATM | path | integer | Sí |  |

Body `CuadreATMCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| fechaContable | string | Sí |  |
| saldoInicial | number | Sí |  |

```json
{
  "fechaContable": "2026-11-04",
  "saldoInicial": 150.0
}
```

## Response `201`

`CuadreATM`

```json
{
  "idCuadreATM": 81,
  "idATM": 1,
  "fechaContable": "2026-11-10",
  "saldoInicial": 2000.0,
  "totalDepositos": 0.0,
  "totalRetiros": 200.0,
  "saldoFinalTeorico": 1800.0,
  "estadoCuadre": "PENDIENTE_ARQUEO"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUADRE_YA_EXISTE` | Ya hay un cuadre para ese ATM y fecha contable (único por ATM y fecha) |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- validación del saldo inicial, fecha contable y estado inicial del cuadre.
