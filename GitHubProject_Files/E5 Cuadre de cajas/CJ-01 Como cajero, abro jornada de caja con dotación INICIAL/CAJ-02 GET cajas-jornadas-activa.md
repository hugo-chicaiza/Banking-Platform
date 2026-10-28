---
number: 160
title: "CAJ-04 | GET /api/v1/caja/jornadas/actual"
type: api
code: CAJ-02
parent: "[[CJ-01 Como cajero, abro jornada de caja con dotación INICIAL]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/160
---

`GET /api/v1/caja/jornadas/actual` · **Roles:** CAJERO · **Historia:** CJ-01 (#51) · **OpenAPI:** `CAJ04`

Jornada abierta del cajero autenticado.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.JornadasCaja` | — | — |

## Reglas de negocio

1. Jornada `ABIERTA` del cajero del token; si no tiene → `404 SIN_JORNADA_ABIERTA`.
2. Incluye totales del día y si ya tiene dotación INICIAL.

## Request

Sin body ni parámetros.

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
| 404 | `SIN_JORNADA_ABIERTA` | El cajero no tiene jornada ABIERTA |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
