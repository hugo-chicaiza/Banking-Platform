---
number: 212
title: "CAJ-16 | PUT /api/v1/caja/jornadas/{idJornada}/cuadre/conteo"
type: api
code: CAJ-16
parent: "[[CJ-03 Como cajero, hago el cuadre de caja (conteo físico vs]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/212
---

`PUT /api/v1/caja/jornadas/{idJornada}/cuadre/conteo` · **Roles:** CAJERO · **Historia:** CJ-03 (#53) · **OpenAPI:** `CAJ16`

Registra el conteo físico final y calcula diferencia/estado.

| Lee | Escribe | DB |
|---|---|---|
| — | `Caja.CuadreCaja` | `Caja.trg_CuadreCaja_Totales` |

## Reglas de negocio

1. `DiferenciaDinero = físico - (inicial + dotaciones + depósitos + pagos - retiros - devoluciones)`; 0 → CUADRADO, > 0 → SOBRANTE, < 0 → FALTANTE.
2. El trigger exige que los totales coincidan con los movimientos reales (DB 54001).
3. Cuadre autorizado o jornada cerrada → `409 CUADRE_YA_CERRADO`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `ConteoFisico`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| saldoFinalFisico | number | Sí | >= 0 |
| observaciones | string(500) | No |  |

```json
{
  "saldoFinalFisico": 150.0,
  "observaciones": "observaciones"
}
```

## Response `200`

`CuadreCaja`

```json
{
  "idCuadreCaja": 1,
  "idJornadaCaja": 1,
  "idUsuario": 1,
  "fechaHoraCuadre": "2026-11-04T10:15:00-05:00",
  "saldoInicial": 150.0,
  "totalDotaciones": 150.0,
  "totalDepositos": 150.0,
  "totalRetiros": 150.0,
  "totalPagos": 150.0,
  "totalDevolucionesBoveda": 150.0,
  "saldoEsperado": 150.0,
  "saldoFinalFisico": 150.0,
  "diferenciaDinero": 150.0,
  "estadoCuadre": "PENDIENTE",
  "idAutorizadoPor": 1,
  "idFechaContable": 20261104,
  "observaciones": "observaciones"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUADRE_YA_CERRADO` | El cuadre ya fue cerrado |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
