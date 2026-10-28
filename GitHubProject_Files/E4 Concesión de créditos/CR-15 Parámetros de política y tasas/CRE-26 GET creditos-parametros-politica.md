---
number: 100
title: "CRE-26 | GET /api/v1/creditos/parametros-politica"
type: api
code: CRE-26
parent: "[[CR-15 Parámetros de política y tasas]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/100
---

`GET /api/v1/creditos/parametros-politica` · **Roles:** ADMIN, APROBADOR · **Historia:** CR-15 (#73), también CR-02 · **OpenAPI:** `CRE26`

Parámetros de política vigentes.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.ParametroPolitica` | — | — |

## Reglas de negocio

1. Devuelve la versión vigente de cada clave (`Estado = 'Activo'`, dentro de vigencia).
2. Claves que usa la evaluación: `EDAD_MINIMA`, `SCORE_MINIMO`, `CUOTA_INGRESO_MAX`, `MONTO_REVISION_MANUAL`, `VIGENCIA_APROBACION`, `TASA_MAXIMA_<tipo>`.

## Request

Sin body ni parámetros.

## Response `200`

`array`

```json
[
  {
    "idParametro": 1,
    "clave": "string",
    "valor": 100.0,
    "unidad": "Score",
    "descripcion": "string",
    "vigenciaDesde": "2026-11-04",
    "vigenciaHasta": "2026-11-04",
    "estado": "Activo"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
