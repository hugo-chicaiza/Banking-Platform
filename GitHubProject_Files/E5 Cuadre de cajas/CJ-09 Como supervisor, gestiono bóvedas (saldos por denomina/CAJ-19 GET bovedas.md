---
number: 177
title: "BOV-01 | GET /api/v1/boveda/bovedas"
type: api
code: CAJ-19
parent: "[[CJ-09 Como supervisor, gestiono bóvedas (saldos por denomina]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/177
---

`GET /api/v1/boveda/bovedas` · **Roles:** SUPERVISOR, CONTADOR, ADMIN · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV01`

Lista bóvedas.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda` | — | — |

## Reglas de negocio

1. Filtros por agencia y tipo; incluye saldo actual y límites mínimo y máximo.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | query | string | No | Agencia |
| tipo | query | string | No | General/Mayor/Menor |

## Response `200`

`array`

```json
[
  {
    "idBoveda": 1,
    "codigoBoveda": "COD01",
    "tipoBoveda": "General",
    "idAgencia": "001",
    "idBovedaSuperior": null,
    "limiteMaximo": 1000,
    "limiteMinimo": 50,
    "saldoActual": 200,
    "estado": "A",
    "denominaciones": [
      {
        "idDenominacion": 1,
        "cantidadActual": 10,
        "valor": 20,
        "subtotal": 200
      }
    ],
    "totalDesglose": 200
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Errores ampliados: ver la documentación de implementación enlazada al final.

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
