---
number: 203
title: "CON-01 | GET /api/v1/contabilidad/fechas-contables/{fecha}"
type: api
code: CON-01
parent: "[[AC-02 Como sistema, resuelvo la fecha contable de cada opera]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2-3"
start_date: 2026-10-26
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/203
---

`GET /api/v1/contabilidad/fechas-contables/{fecha}` · **Roles:** AUTH · **Historia:** AC-02 (#66) · **OpenAPI:** `CON01`

Fecha contable de una fecha (día hábil, feriado, corte).

| Lee | Escribe | DB |
|---|---|---|
| `Contabilidad.FechaContable`, `Contabilidad.Feriado` | — | `Contabilidad.fn_IdFechaContable` |

## Reglas de negocio

1. Devuelve si el día es contable, si es feriado y la fecha contable que aplica a esa fecha y hora.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| fecha | path | string | Sí |  |

## Response `200`

`FechaContable`

```json
{
  "idFechaContable": 20261104,
  "fecha": "2026-11-04",
  "esDiaContable": true,
  "esFeriado": true,
  "esFinDeSemana": true,
  "horaCorte": "horaCorte"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
