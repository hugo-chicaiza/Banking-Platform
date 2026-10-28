---
number: 130
title: "TAR-02 | GET /api/v1/tarjetas"
type: api
code: TAR-02
parent: "[[A-04 Asociación de tarjeta bancaria]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/130
---

`GET /api/v1/tarjetas` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-04 (#40) · **OpenAPI:** `TAR02`

Busca tarjetas.

| Lee | Escribe | DB |
|---|---|---|
| `Tarjeta.Tarjeta` | — | — |

## Reglas de negocio

1. Solo número enmascarado; nunca PAN, token ni hash.
2. Filtros combinables; paginado (máx. 100).

## Flujo

1. El asesor accede a la sección de consulta de tarjetas.
2. El frontend presenta los filtros de búsqueda disponibles.
3. El asesor introduce uno o varios criterios de búsqueda.
4. El frontend envía una solicitud `GET /api/v1/tarjetas` con los parámetros seleccionados.
5. El backend valida la autenticación y los permisos del usuario.
6. El sistema consulta las tarjetas registradas aplicando los filtros y restricciones de acceso.
7. El backend organiza los resultados mediante la paginación y el ordenamiento solicitados.
8. El sistema devuelve la lista de tarjetas encontradas con sus datos autorizados.
9. El frontend presenta los resultados.
10. El asesor puede seleccionar una tarjeta para consultar su detalle mediante `TAR-03`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | query | integer | No | Cliente |
| idCuenta | query | integer | No | Cuenta |
| estado | query | string | No | Estado actual |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageTarjeta`

```json
{
  "items": [
    {
      "idTarjeta": 301,
      "idCliente": 125,
      "idCuenta": 501,
      "idProducto": 3,
      "tipoTarjeta": "Debito",
      "nombreTarjeta": "MARIA MENDOZA",
      "numeroEnmascarado": "4540 12** **** 3456",
      "estadoActual": "PENDIENTE_ACTIVACION",
      "fechaEmision": "2026-10-26"
    },
    {
      "idTarjeta": 302,
      "idCliente": 125,
      "idCuenta": 501,
      "idProducto": 3,
      "tipoTarjeta": "Debito",
      "nombreTarjeta": "MARIA MENDOZA",
      "numeroEnmascarado": "4540 12** **** 7890",
      "estadoActual": "ACTIVA",
      "fechaEmision": "2026-09-15"
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
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
