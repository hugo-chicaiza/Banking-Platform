---
number: 165
title: "CAJ-14 | GET /api/v1/caja/jornadas/{idJornada}/cuadre"
type: api
code: CAJ-07
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/165
---

`GET /api/v1/caja/jornadas/{idJornada}/cuadre` · **Roles:** CAJERO, SUPERVISOR, CONTADOR · **Historia:** CJ-03 (#53) · **OpenAPI:** `CAJ14`

Consulta el cuadre de la jornada.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CuadreCaja` | — | — |

## Reglas de negocio

1. Muestra totales, conteo, diferencia, estado y autorizador.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

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

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
