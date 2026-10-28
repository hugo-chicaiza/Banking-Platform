---
number: 125
title: "CTA-02 | GET /api/v1/cuentas"
type: api
code: CTA-02
parent: "[[A-02 Consulta de saldo y estado de cuenta]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/125
---

`GET /api/v1/cuentas` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** A-02 (#18) · **OpenAPI:** `CTA02`

Busca cuentas.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta` | — | — |

## Reglas de negocio

1. Filtros opcionales y combinables; paginado (máx. 100).
2. `numeroCuenta` es búsqueda exacta.

## Flujo

1. El asesor accede a la sección de consulta de cuentas.
2. El frontend presenta los filtros de búsqueda disponibles.
3. El asesor introduce uno o varios criterios de búsqueda.
4. El frontend envía una solicitud `GET /api/v1/cuentas` con los parámetros seleccionados.
5. El backend valida la autenticación y los permisos del usuario.
6. El sistema consulta `Cuentas.Cuenta` aplicando los filtros autorizados.
7. El backend organiza los resultados según el orden y la paginación solicitados.
8. El sistema devuelve la lista de cuentas encontradas.
9. El frontend presenta los resultados.
10. El asesor selecciona una cuenta para consultar su información general o sus saldos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | query | integer | No | Cliente |
| numeroCuenta | query | string | No | Exacto |
| estado | query | string | No | Estado |
| idAgencia | query | string | No | Agencia |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageCuenta`

```json
{
  "items": [
    {
      "idCuenta": 501,
      "numeroCuenta": "AH000501",
      "idCliente": 125,
      "idProducto": 2,
      "idAgencia": "001",
      "tipoCuenta": "Ahorro",
      "estado": "ACTIVA"
    },
    {
      "idCuenta": 502,
      "numeroCuenta": "AH000502",
      "idCliente": 125,
      "idProducto": 2,
      "idAgencia": "001",
      "tipoCuenta": "Ahorro",
      "estado": "ACTIVA"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 2
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
