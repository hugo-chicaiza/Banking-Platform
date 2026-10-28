---
number: 205
title: "CON-02 | GET /api/v1/contabilidad/fechas-contables/actual"
type: api
code: CON-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/205
---

`GET /api/v1/contabilidad/fechas-contables/actual` · **Roles:** AUTH · **Historia:** AC-02 (#66) · **OpenAPI:** `CON02`

Fecha contable vigente (según hora de corte).

| Lee | Escribe | DB |
|---|---|---|
| `Contabilidad.FechaContable` | — | `Contabilidad.fn_IdFechaContable` |

## Reglas de negocio

1. Antes de la hora de corte (19:00) de un día hábil → hoy; después, en fin de semana o feriado → el siguiente día contable.
2. Si el calendario no tiene la fecha cargada → 500 y alerta (DB 51016).

## Request

Sin body ni parámetros.

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

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
