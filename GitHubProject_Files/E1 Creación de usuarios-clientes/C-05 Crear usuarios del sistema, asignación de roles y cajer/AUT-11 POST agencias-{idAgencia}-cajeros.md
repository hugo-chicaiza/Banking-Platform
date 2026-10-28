---
number: 195
title: "AUT-11 | POST /api/v1/agencias/{idAgencia}/cajeros"
type: api
code: AUT-11
parent: "[[C-05 Crear usuarios del sistema, asignación de roles y cajer]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/195
---

`POST /api/v1/agencias/{idAgencia}/cajeros` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT11`

Asigna un cajero a la agencia.

| Lee | Escribe | DB |
|---|---|---|
| — | `Caja.CajerosAsignadosAgencia` | — |

## Reglas de negocio

1. El usuario debe existir, estar `Activo` y tener rol CAJERO → si no, 422.
2. Un cajero solo tiene una asignación vigente: si ya está vigente en esta agencia → `409 CAJERO_YA_ASIGNADO`; si está en otra, se cierra esa (`FechaFin`, `Estado = 0`) y se crea la nueva.
3. `AsignadoPor` sale del token; `motivo` es opcional (máx. 250).
4. La agencia debe estar activa (`Estado = 'A'`).

## Flujo

1. Validar agencia, usuario y rol.
2. Cerrar la asignación vigente anterior, si existe, e insertar la nueva en una transacción.
3. Responder 201 con la asignación.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idAgencia | path | string | Sí |  |

Body `AsignacionAgenciaCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idUsuario | integer | Sí |  |
| fechaInicio | string | Sí |  |
| motivo | string | No |  |

```json
{
  "idUsuario": 1,
  "fechaInicio": "2026-11-04T10:15:00-05:00",
  "motivo": "Solicitud del cliente"
}
```

## Response `201`

`AsignacionAgencia`

```json
{
  "idHistorialUsuarioAgencia": 1,
  "idUsuario": 1,
  "idAgencia": "001",
  "fechaInicio": "2026-11-04T10:15:00-05:00",
  "fechaFin": "2026-11-04T10:15:00-05:00",
  "asignadoPor": 12,
  "estado": "Activo"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CAJERO_YA_ASIGNADO` | El cajero ya tiene una asignación vigente en esta agencia |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
