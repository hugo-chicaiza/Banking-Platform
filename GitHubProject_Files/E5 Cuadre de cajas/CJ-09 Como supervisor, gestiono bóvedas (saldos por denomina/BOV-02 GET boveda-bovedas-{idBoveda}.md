---
number: 215
title: "BOV-02 | GET /api/v1/boveda/bovedas/{idBoveda}"
type: api
code: BOV-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/215
---

`GET /api/v1/boveda/bovedas/{idBoveda}` · **Roles:** SUPERVISOR, CONTADOR, ADMIN · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV02`

Bóveda con saldo por denominación.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda`, `Boveda.BovedaDenominacion` | — | — |

## Reglas de negocio

1. Saldo por denominación (`BovedaDenominacion`) y totales.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |

## Response `200`

`Boveda`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Errores ampliados: ver la documentación de implementación enlazada al final.

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
