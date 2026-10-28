---
number: 188
title: "CLI-07 | GET /api/v1/clientes/{idCliente}/historial"
type: api
code: CLI-07
parent: "[[C-04 Edición de los datos del cliente y cambio de estado (Ac]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/188
---

`GET /api/v1/clientes/{idCliente}/historial` · **Roles:** SUPERVISOR, AUDITOR, ADMIN · **Historia:** C-04 (#47) · **OpenAPI:** `CLI07`

Historial de cambios del cliente.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.ClientesHis` | — | `Clientes.trg_ClientesHis_Inmutable` |

## Reglas de negocio

1. Orden por fecha descendente; paginado (máx. 100).
2. `ClientesHis` es inmutable (`trg_ClientesHis_Inmutable`, error 57001).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageClienteHistorial`

```json
{
  "items": [
    {
      "idHistorial": 1,
      "tipoOperacion": "I",
      "campoModificado": "campoModificado",
      "valorAnterior": "valorAnterior",
      "modificadoPor": 12,
      "direccionIP": "direccionIP",
      "fechaModificacion": "2026-11-04T10:15:00-05:00",
      "observaciones": "observaciones"
    }
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
