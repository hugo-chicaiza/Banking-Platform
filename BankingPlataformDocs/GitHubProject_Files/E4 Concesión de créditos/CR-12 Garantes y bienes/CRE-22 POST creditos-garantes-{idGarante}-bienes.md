---
number: 96
title: "CRE-22 | POST /api/v1/creditos/garantes/{idGarante}/bienes"
type: api
code: CRE-22
parent: "[[CR-12 Garantes y bienes]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/96
---

`POST /api/v1/creditos/garantes/{idGarante}/bienes` · **Roles:** ASESOR · **Historia:** CR-12 (#70) · **OpenAPI:** `CRE22`

Registra un bien del garante.

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.GaranteBien` | — |

## Reglas de negocio

1. Bien inmueble exige datos de escritura → `422 ESCRITURA_INCOMPLETA`; avalúo > 0.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idGarante | path | integer | Sí |  |

Body `GaranteBienCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoBien | Inmueble \| Vehiculo \| Otro | Sí |  |
| descripcion | string | Sí |  |
| valorAvaluo | number | Sí |  |
| gravamen | Libre \| Hipotecado \| Prendado | No |  |
| tieneEscritura | boolean | No |  |
| numeroEscritura | string | No |  |
| notaria | string | No |  |
| fechaEscritura | string | No |  |
| registroPropiedad | string | No |  |

```json
{
  "tipoBien": "Inmueble",
  "descripcion": "string",
  "valorAvaluo": 100.0,
  "gravamen": "Libre",
  "tieneEscritura": true,
  "numeroEscritura": "string",
  "notaria": "string",
  "fechaEscritura": "2026-11-04",
  "registroPropiedad": "string"
}
```

## Response `201`

`GaranteBien`

```json
{
  "idGaranteBien": 1,
  "tipoBien": "string",
  "descripcion": "string",
  "valorAvaluo": 100.0,
  "gravamen": "string",
  "tieneEscritura": true,
  "estado": "A"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `ESCRITURA_INCOMPLETA` | El bien inmueble no trae datos de escritura |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
