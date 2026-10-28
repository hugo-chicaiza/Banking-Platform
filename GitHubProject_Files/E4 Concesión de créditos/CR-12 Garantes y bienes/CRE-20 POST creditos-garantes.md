---
number: 94
title: "CRE-20 | POST /api/v1/creditos/garantes"
type: api
code: CRE-20
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/94
---

`POST /api/v1/creditos/garantes` · **Roles:** ASESOR · **Historia:** CR-12 (#70) · **OpenAPI:** `CRE20`

Registra un garante.

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.Garante` | — |

## Reglas de negocio

1. Identificación única → `409 GARANTE_DUPLICADO`.
2. El garante no puede ser el mismo cliente que pide el crédito (DB 55001/55002).
3. `origen` (cliente existente o externo) válido → `422 ORIGEN_INVALIDO`.

## Request

Body `GaranteCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCliente | integer | No | Si es cliente del banco |
| identificacion | string(13) | Sí |  |
| nombres | string | Sí |  |
| apellidos | string | No |  |
| telefonoCelular | string(15) | Sí |  |
| email | string | No |  |
| ingresoMensual | number | No |  |
| esExterno | boolean | Sí | true = no cliente (idCliente debe ir vacío) |

```json
{
  "idCliente": 1,
  "identificacion": "string",
  "nombres": "string",
  "apellidos": "string",
  "telefonoCelular": "string",
  "email": "string",
  "ingresoMensual": 100.0,
  "esExterno": true
}
```

## Response `201`

`Garante`

```json
{
  "idGarante": 1,
  "idCliente": 1,
  "identificacion": "string",
  "nombres": "string",
  "apellidos": "string",
  "telefonoCelular": "string",
  "email": "string",
  "ingresoMensual": 100.0,
  "esExterno": true,
  "bienes": [
    {
      "idGaranteBien": 1,
      "tipoBien": "string",
      "descripcion": "string",
      "valorAvaluo": 100.0,
      "gravamen": "string",
      "tieneEscritura": true,
      "estado": "A"
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `GARANTE_DUPLICADO` | Ya existe un garante con esa identificación |
| 422 | `ORIGEN_INVALIDO` | El origen del asiento no admite esta operación |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
