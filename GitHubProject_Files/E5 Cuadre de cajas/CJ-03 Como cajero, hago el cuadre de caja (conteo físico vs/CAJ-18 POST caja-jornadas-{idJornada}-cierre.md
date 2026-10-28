---
number: 213
title: "CAJ-18 | POST /api/v1/caja/jornadas/{idJornada}/cierre"
type: api
code: CAJ-18
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/213
---

`POST /api/v1/caja/jornadas/{idJornada}/cierre` · **Roles:** CAJERO · **Historia:** CJ-03 (#53) · **OpenAPI:** `CAJ18`

Cierra la jornada.

| Lee | Escribe | DB |
|---|---|---|
| — | `Caja.JornadasCaja` | — |

## Reglas de negocio

1. Exige cuadre con conteo y, si hay diferencia, autorización → `409 CUADRE_NO_AUTORIZADO`.
2. Pasa la jornada a `CERRADA` (terminal) → si ya lo está, `409 JORNADA_YA_CERRADA`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

## Response `200`

`Jornada`

```json
{
  "idJornadaCaja": 1,
  "idUsuario": 1,
  "idCajaFisica": 1,
  "idAgencia": "001",
  "fechaHoraApertura": "2026-11-04T10:15:00-05:00",
  "fechaHoraCierre": "2026-11-04T10:15:00-05:00",
  "dineroInicial": 150.0,
  "estado": "ABIERTA",
  "observacion": "Operación de prueba"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUADRE_NO_AUTORIZADO` | El cuadre no tiene autorización del supervisor |
| 409 | `JORNADA_YA_CERRADA` | La jornada ya está CERRADA |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
