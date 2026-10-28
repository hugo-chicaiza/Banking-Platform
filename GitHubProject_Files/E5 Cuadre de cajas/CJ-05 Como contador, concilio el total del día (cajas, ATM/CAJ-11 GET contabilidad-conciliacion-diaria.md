---
number: 169
title: "CON-07 | GET /api/v1/contabilidad/conciliacion"
type: api
code: CAJ-11
parent: "[[CJ-05 Como contador, concilio el total del día (cajas, ATM]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/169
---

`GET /api/v1/contabilidad/conciliacion` · **Roles:** CONTADOR, SUPERVISOR · **Historia:** CJ-05 (#55) · **OpenAPI:** `CON07`

Conciliación diaria: operativo vs contable.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CuadreCaja`, `ATM.CuadreATM`, `Transacciones.Transaccion`, `Credito.CreditoCuotaPago`, `Boveda.MovimientoBoveda`, `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables` | — | `Contabilidad.usp_ValidarCierreDiario`, `Contabilidad.vw_ConciliacionEfectivo`, `Contabilidad.vw_TransaccionesSinAsiento` |

## Reglas de negocio

1. Por fecha contable y agencia compara caja, ATM, crédito y bóveda contra sus asientos; cuadrada si todas las diferencias son 0.
2. Usa `vw_ConciliacionEfectivo` (cuenta 110105 vs efectivo) y `vw_TransaccionesSinAsiento`.
3. Solo lectura. `usp_ValidarCierreDiario` con `@Bloquear = 0` devuelve los hallazgos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| fechaContable | query | string | Sí | Fecha contable |
| idAgencia | query | string | No | Agencia |

## Response `200`

`ConciliacionDiaria`

```json
{
  "fechaContable": "2026-11-04",
  "idAgencia": "001",
  "cajas": {
    "totalOperativo": 150.0,
    "totalContable": 150.0,
    "diferencia": 150.0,
    "operaciones": 12
  },
  "atm": {
    "totalOperativo": 150.0,
    "totalContable": 150.0,
    "diferencia": 150.0,
    "operaciones": 12
  },
  "creditos": {
    "totalOperativo": 150.0,
    "totalContable": 150.0,
    "diferencia": 150.0,
    "operaciones": 12
  },
  "boveda": {
    "totalOperativo": 150.0,
    "totalContable": 150.0,
    "diferencia": 150.0,
    "operaciones": 12
  },
  "asientosDebito": 150.0,
  "asientosCredito": 150.0,
  "diferenciaGlobal": 150.0,
  "cuadrada": true,
  "detalleDiferencias": [
    {
      "modulo": "modulo",
      "referencia": "Frente al parque",
      "descripcion": "Descripción",
      "monto": 150.0
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- G-07: decidir si se guarda el resultado de la conciliación.
