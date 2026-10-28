---
number: 137
title: "CTA-09 | GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial"
type: api
code: CTA-09
parent: "[[A-06 Configuración de cupos por canal]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/137
---

`GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial` · **Roles:** SUPERVISOR, AUDITOR, ADMIN · **Historia:** A-06 (#62) · **OpenAPI:** `CTA09`

Historial de cambios de cupo.

| Lee | Escribe | DB |
|---|---|---|
| `Canal.CuposModHis` | — | — |

## Reglas de negocio

1. Orden por fecha descendente; paginado (máx. 100).

## Flujo

1. El cliente inicia sesión en la aplicación bancaria.
2. Accede a sus cuentas y selecciona la cuenta correspondiente.
3. Consulta los cupos vigentes mediante `CTA-07`.
4. Selecciona el canal cuyo historial desea revisar.
5. El frontend envía la solicitud `GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial`.
6. El backend valida la autenticación y los permisos del usuario.
7. Verifica que el cliente tenga autorización sobre la cuenta.
8. El sistema consulta los registros históricos de `Canal.CuposModHis`.
9. Filtra los registros por cuenta y canal.
10. Aplica el ordenamiento y la paginación solicitados.
11. Devuelve los registros históricos encontrados.
12. El frontend presenta los cambios realizados sobre el cupo.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |
| idCanal | path | integer | Sí |  |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageCupoHistorial`

```json
{
  "items": [
    {
      "idCupoModHis": 103,
      "cupoDiarioAnterior": 300.0,
      "cupoDiarioNuevo": 400.0,
      "cupoMensualAnterior": 4000.0,
      "cupoMensualNuevo": 5000.0,
      "montoMaxTxAnterior": 150.0,
      "montoMaxTxNuevo": 200.0,
      "modificadoPor": 125,
      "fechaModificacion": "2026-10-26T15:30:00-05:00"
    },
    {
      "idCupoModHis": 102,
      "cupoDiarioAnterior": 500.0,
      "cupoDiarioNuevo": 300.0,
      "cupoMensualAnterior": 5000.0,
      "cupoMensualNuevo": 4000.0,
      "montoMaxTxAnterior": 200.0,
      "montoMaxTxNuevo": 150.0,
      "modificadoPor": 125,
      "fechaModificacion": "2026-10-20T10:15:00-05:00"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 2
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
