---
number: 167
title: "CAJ-02 | GET /api/v1/caja/jornadas"
type: api
code: CAJ-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/167
---

`GET /api/v1/caja/jornadas` · **Roles:** SUPERVISOR, CONTADOR, AUDITOR · **Historia:** CJ-03 (#53) · **OpenAPI:** `CAJ02`

Consulta jornadas.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.JornadasCaja` | — | — |

## Reglas de negocio

1. Filtros por agencia, cajero, estado y rango de fechas; paginado (máx. 100).
2. Incluye el estado del cuadre de cada jornada.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | query | string | No | Agencia |
| idUsuario | query | integer | No | Cajero |
| estado | query | string | No | ABIERTA/CERRADA/CANCELADA |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageJornada`

```json
{
  "items": [
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
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
