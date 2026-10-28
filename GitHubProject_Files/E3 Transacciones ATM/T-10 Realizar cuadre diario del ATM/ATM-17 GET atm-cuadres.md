---
number: 155
title: "ATM-17 | GET /api/v1/atm/cuadres"
type: api
code: ATM-17
parent: "[[T-10 Realizar cuadre diario del ATM]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/155
---

`GET /api/v1/atm/cuadres` · **Roles:** SUPERVISOR, CONTADOR, AUDITOR · **Historia:** T-10 (#103), también CJ-05 · **OpenAPI:** `ATM17`

Consulta cuadres.

| Lee | Escribe | DB |
|---|---|---|
| `ATM.CuadreATM` | — | — |

## Reglas de negocio

1. Filtros por ATM, fecha contable y estado; paginado. Lo usa la conciliación (CJ-05).

## Flujo

1. El usuario aplica filtros de ATM, fecha, estado y paginación.
2. Backend valida SUPERVISOR, CONTADOR o AUDITOR y filtra por alcance autorizado.
3. Devuelve una página de cuadres.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idATM | query | integer | No | ATM |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| estado | query | string | No | Estado |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageCuadreATM`

```json
{
  "items": [
    {
      "idCuadreATM": 81,
      "idATM": 1,
      "fechaContable": "2026-11-10",
      "saldoInicial": 2000.0,
      "totalDepositos": 0.0,
      "totalRetiros": 200.0,
      "saldoFinalTeorico": 1800.0,
      "saldoFinalFisico": 1800.0,
      "diferencia": 0.0,
      "estadoCuadre": "CERRADO"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- valores predeterminados de paginación, campos ordenables y alcance por agencia.
