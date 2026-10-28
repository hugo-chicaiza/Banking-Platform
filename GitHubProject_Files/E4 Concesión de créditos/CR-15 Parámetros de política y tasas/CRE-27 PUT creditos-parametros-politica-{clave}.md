---
number: 101
title: "CRE-27 | PUT /api/v1/creditos/parametros-politica/{clave}"
type: api
code: CRE-27
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/101
---

`PUT /api/v1/creditos/parametros-politica/{clave}` · **Roles:** ADMIN · **Historia:** CR-15 (#73) · **OpenAPI:** `CRE27`

Actualiza un parámetro (cierra el anterior y abre uno nuevo).

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.ParametroPolitica` | — |

## Reglas de negocio

1. Cierra la versión vigente (`VigenciaHasta = ahora`) y crea una nueva con el valor; nunca edita en el lugar.
2. Clave inexistente → 404; valor fuera de rango para la clave → 422.

## Flujo

1. Validar clave y valor.
2. Cerrar la versión vigente y crear la nueva en una transacción.
3. Responder 200 con el parámetro vigente.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| clave | path | string | Sí |  |

Body `ParametroPolitica`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idParametro | integer | No |  |
| clave | string | Sí |  |
| valor | number | Sí |  |
| unidad | Score \| Dias \| Anios \| Meses \| Porcentaje \| Monto | Sí |  |
| descripcion | string | No |  |
| vigenciaDesde | string | Sí |  |
| vigenciaHasta | string | No |  |
| estado | Activo \| Inactivo | No |  |

```json
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
```

## Response `200`

`ParametroPolitica`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
