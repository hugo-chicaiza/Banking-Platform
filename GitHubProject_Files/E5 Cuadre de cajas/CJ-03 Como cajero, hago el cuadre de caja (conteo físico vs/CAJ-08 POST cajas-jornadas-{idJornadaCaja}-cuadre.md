---
number: 166
title: "CAJ-13 | POST /api/v1/caja/jornadas/{idJornada}/cuadre"
type: api
code: CAJ-08
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/166
---

`POST /api/v1/caja/jornadas/{idJornada}/cuadre` · **Roles:** CAJERO · **Historia:** CJ-03 (#53) · **OpenAPI:** `CAJ13`

Genera el cuadre (totales calculados, estado PENDIENTE).

| Lee | Escribe | DB |
|---|---|---|
| `Caja.MovimientosCaja`, `Caja.DotacionesCaja`, `Caja.DevolucionesCaja` | `Caja.CuadreCaja` | — |

## Reglas de negocio

1. Un cuadre por jornada → `409 CUADRE_YA_EXISTE`; jornada cancelada → `409 JORNADA_CANCELADA`.
2. Calcula los totales (dotaciones, depósitos, pagos, retiros) y nace en `PENDIENTE` sin conteo.
3. Flujo de cierre (brecha G-09): cuadre PENDIENTE → devolución (CAJ-15) → conteo (CAJ-16) → autorización (CAJ-17) → cierre (CAJ-18).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `CuadreCajaCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| observaciones | string(500) | No |  |

```json
{
  "observaciones": "observaciones"
}
```

## Response `201`

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
| 409 | `CUADRE_YA_EXISTE` | Ya hay un cuadre para ese ATM y fecha contable (1 por jornada) |
| 409 | `JORNADA_CANCELADA` | La jornada está CANCELADA |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
