---
number: 131
title: "TAR-03 | GET /api/v1/tarjetas/{idTarjeta}"
type: api
code: TAR-03
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/131
---

`GET /api/v1/tarjetas/{idTarjeta}` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-04 (#40) · **OpenAPI:** `TAR03`

Detalle de tarjeta.

| Lee | Escribe | DB |
|---|---|---|
| `Tarjeta.Tarjeta` | — | — |

## Reglas de negocio

1. Tarjeta inexistente → 404. Solo número enmascarado.

## Flujo

1. El asesor accede a la sección de consulta de tarjetas.
2. Busca la tarjeta mediante `TAR-02 | GET /api/v1/tarjetas`.
3. Selecciona la tarjeta que desea consultar.
4. El frontend obtiene el identificador `idTarjeta`.
5. Envía la solicitud `GET /api/v1/tarjetas/{idTarjeta}`.
6. El backend valida la autenticación y los permisos del usuario.
7. El sistema verifica que la tarjeta exista.
8. Consulta la información registrada de la tarjeta.
9. El backend excluye los datos sensibles de la respuesta.
10. Devuelve los datos generales, la cuenta asociada y el estado actual.
11. El frontend presenta la información al asesor.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |

## Response `200`

`Tarjeta`

```json
{
  "idTarjeta": 1,
  "tokenTarjeta": "TOKEN_FICTICIO",
  "numeroEnmascarado": "numeroEnmascarado",
  "tipoTarjeta": "tipoTarjeta",
  "nombreTarjeta": "nombreTarjeta",
  "idCliente": 1,
  "idCuenta": 1,
  "idProducto": 1,
  "estadoActual": "estadoActual",
  "pinAsignado": true,
  "fechaEmision": "2026-11-04",
  "fechaExpiracion": "2026-11-04"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
