---
number: 216
title: "BOV-03 | GET /api/v1/boveda/bovedas/{idBoveda}/movimientos"
type: api
code: BOV-03
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/216
---

`GET /api/v1/boveda/bovedas/{idBoveda}/movimientos` · **Roles:** SUPERVISOR, CONTADOR, AUDITOR · **Historia:** CJ-09 (#63) · **OpenAPI:** `BOV03`

Movimientos de bóveda.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.MovimientoBoveda` | — | — |

## Reglas de negocio

1. Filtros por tipo y rango de fechas; paginado. Cada movimiento con naturaleza I/E y desglose.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |
| tipoMovimiento | query | string | No | Tipo |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageMovimientoBoveda`

```json
{
  "items": [
    {
      "idMovimiento": 1,
      "idBoveda": 1,
      "idBovedaContraparte": null,
      "tipoMovimiento": "ProvisionExterna",
      "naturaleza": "I",
      "monto": 40,
      "saldoAnterior": 200,
      "saldoPosterior": 240,
      "autorizadoPor": 9,
      "idUsuarioMovimiento": 7,
      "idMovimientoRelacionado": null,
      "fechaMovimiento": "2026-11-16T10:00:00-05:00",
      "observaciones": null,
      "idAsientoContable": 1,
      "desglose": [
        {
          "idDenominacion": 1,
          "cantidad": 2
        }
      ]
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Errores ampliados: ver la documentación de implementación enlazada al final.

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
