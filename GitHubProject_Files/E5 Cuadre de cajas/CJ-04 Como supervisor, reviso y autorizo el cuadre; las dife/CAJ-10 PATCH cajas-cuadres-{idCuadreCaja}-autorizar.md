---
number: 168
title: "CAJ-17 | POST /api/v1/caja/jornadas/{idJornada}/cuadre/autorizacion"
type: api
code: CAJ-10
parent: "[[CJ-04 Como supervisor, reviso y autorizo el cuadre; las dife]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/168
---

`POST /api/v1/caja/jornadas/{idJornada}/cuadre/autorizacion` · **Roles:** SUPERVISOR · **Historia:** CJ-04 (#54) · **OpenAPI:** `CAJ17`

El supervisor autoriza el cuadre.

| Lee | Escribe | DB |
|---|---|---|
| — | `Caja.CuadreCaja` | — |

## Reglas de negocio

1. El supervisor no es el cajero → `409 DOBLE_CUSTODIA_VIOLADA`.
2. Exige conteo registrado → `409 CUADRE_PENDIENTE_DE_CONTEO`.
3. No hay estado APROBADO: se fija `IdAutorizadoPor`. SOBRANTE o FALTANTE exigen observación.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `AutorizacionCuadre`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| autorizadoPor | integer | Sí | Distinto del cajero |
| observaciones | string(500) | No |  |

```json
{
  "autorizadoPor": 12,
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
| 409 | `DOBLE_CUSTODIA_VIOLADA` | Quien autoriza es el mismo que opera |
| 409 | `CUADRE_PENDIENTE_DE_CONTEO` | El cuadre no tiene conteo físico |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
