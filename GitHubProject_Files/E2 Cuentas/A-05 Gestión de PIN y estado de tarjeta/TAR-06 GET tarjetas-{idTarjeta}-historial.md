---
number: 134
title: "TAR-06 | GET /api/v1/tarjetas/{idTarjeta}/historial"
type: api
code: TAR-06
parent: "[[A-05 Gestión de PIN y estado de tarjeta]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/134
---

`GET /api/v1/tarjetas/{idTarjeta}/historial` · **Roles:** SUPERVISOR, AUDITOR, ADMIN · **Historia:** A-05 (#59) · **OpenAPI:** `TAR06`

Historial de eventos de la tarjeta.

| Lee | Escribe | DB |
|---|---|---|
| `Tarjeta.TarjetaHis` | — | — |

## Reglas de negocio

1. Orden por fecha descendente; paginado (máx. 100). `TarjetaHis` es inmutable.

## Flujo

1. El asesor accede a la sección de consulta de tarjetas.
2. Busca y selecciona la tarjeta mediante `TAR-02`.
3. Consulta su información general mediante `TAR-03`.
4. Selecciona la opción de consultar historial.
5. El frontend envía la solicitud `GET /api/v1/tarjetas/{idTarjeta}/historial`.
6. El backend valida la autenticación y los permisos del usuario.
7. El sistema verifica que la tarjeta exista.
8. Consulta los eventos registrados en `Tarjeta.TarjetaHis`.
9. Aplica los filtros de fecha, paginación y ordenamiento solicitados.
10. Excluye cualquier información sensible de la respuesta.
11. Devuelve los registros históricos encontrados.
12. El frontend presenta el historial de operaciones de la tarjeta.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageTarjetaHistorial`

```json
{
  "items": [
    {
      "idHistorial": 103,
      "idTarjeta": 301,
      "tipoEvento": "CAMBIO_ESTADO",
      "estadoAnterior": "BLOQUEADA",
      "estadoNuevo": "ACTIVA",
      "motivo": "Desbloqueo autorizado.",
      "fechaCambio": "2026-10-26T15:30:00-05:00",
      "realizadoPor": 12
    },
    {
      "idHistorial": 102,
      "idTarjeta": 301,
      "tipoEvento": "CAMBIO_ESTADO",
      "estadoAnterior": "ACTIVA",
      "estadoNuevo": "BLOQUEADA",
      "motivo": "Solicitud del titular por posible extravío.",
      "fechaCambio": "2026-10-25T10:15:00-05:00",
      "realizadoPor": 12
    },
    {
      "idHistorial": 101,
      "idTarjeta": 301,
      "tipoEvento": "ASIGNACION_PIN",
      "resultado": "COMPLETADO",
      "fechaCambio": "2026-10-24T09:00:00-05:00",
      "realizadoPor": 15
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 3
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
