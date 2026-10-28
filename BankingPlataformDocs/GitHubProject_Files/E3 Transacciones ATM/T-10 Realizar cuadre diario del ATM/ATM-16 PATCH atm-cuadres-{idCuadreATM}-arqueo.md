---
number: 154
title: "ATM-16 | PATCH /api/v1/atm/cuadres/{idCuadreATM}/arqueo"
type: api
code: ATM-16
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/154
---

`PATCH /api/v1/atm/cuadres/{idCuadreATM}/arqueo` · **Roles:** SUPERVISOR · **Historia:** T-10 (#103) · **OpenAPI:** `ATM16`

Registra el conteo físico y cierra el cuadre.

| Lee | Escribe | DB |
|---|---|---|
| — | `ATM.CuadreATM` | — |

## Reglas de negocio

1. Registra `SaldoFinalFisico` y `Diferencia = físico - teórico`: 0 → `CUADRADO`; otro valor → `CON_DIFERENCIA`.
2. Con diferencia exige observación y `IdAutorizadoPor` distinto del responsable.
3. El remanente vuelve a bóveda como `RemanenteATM`.

## Flujo

1. SUPERVISOR ingresa el efectivo contado y observaciones.
2. Backend valida el estado del cuadre, calcula la diferencia y aplica el cierre acordado.
3. Devuelve el cuadre actualizado; la transición exacta debe acordarse.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuadreATM | path | integer | Sí |  |

Body `CuadreATMArqueo`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| saldoFinalFisico | number | Sí |  |
| observaciones | string(500) | No |  |

```json
{
  "saldoFinalFisico": 150.0,
  "observaciones": "observaciones"
}
```

## Response `200`

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
  "saldoFinalFisico": 1800.0,
  "diferencia": 0.0,
  "estadoCuadre": "CERRADO"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- fórmula y signo de diferencia, transiciones de estado y modificación de cuadres cerrados.
