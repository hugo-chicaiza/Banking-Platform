---
number: 174
title: "CAJ-10 | POST /api/v1/caja/depositos/{idTransaccion}/series"
type: api
code: CAJ-16
parent: "[[CJ-07 Como cajero, registro un depósito en ventanilla con de]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/174
---

`POST /api/v1/caja/depositos/{idTransaccion}/series` · **Roles:** CAJERO · **Historia:** CJ-07 (#60) · **OpenAPI:** `CAJ10`

Registra series de billetes de $50/$100 del depósito.

| Lee | Escribe | DB |
|---|---|---|
| `Transacciones.Transaccion`, `Catalogo.Denominacion` | `Boveda.BilleteSerie` | `Boveda.usp_RegistrarSeriesBilletes` |

## Reglas de negocio

1. Se ejecuta `Boveda.usp_RegistrarSeriesBilletes` por denominación.
2. Sin series repetidas, cantidad igual a la declarada y valor no mayor al monto del depósito → `422 SERIES_INVALIDAS` (DB 51201-51211).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTransaccion | path | integer | Sí |  |

Body `SeriesBilletesRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idDenominacion | integer | Sí | Billete de $50 o $100 |
| cantidadDeclarada | integer | Sí |  |
| series | string[] | Sí | Máx. 20 caracteres c/u; sin repetidas |

```json
{
  "idDenominacion": 1,
  "cantidadDeclarada": 12,
  "series": [
    "series"
  ]
}
```

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)
