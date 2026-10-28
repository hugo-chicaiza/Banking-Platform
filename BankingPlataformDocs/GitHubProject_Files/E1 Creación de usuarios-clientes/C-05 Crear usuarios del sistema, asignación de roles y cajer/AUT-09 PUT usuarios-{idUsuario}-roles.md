---
number: 193
title: "AUT-09 | PUT /api/v1/usuarios/{idUsuario}/roles"
type: api
code: AUT-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/193
---

`PUT /api/v1/usuarios/{idUsuario}/roles` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT09`

Reemplaza los roles del usuario.

| Lee | Escribe | DB |
|---|---|---|
| — | `Seguridad.GruposUsuarios` | — |

## Reglas de negocio

1. Reemplaza el conjunto completo de roles; la lista no puede estar vacía.
2. Roles válidos: ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR (deben existir en `Seguridad.Grupos`) → si no, 400.
3. Los roles quitados pasan a `Estado = 'Inactivo'` (no se borran); los nuevos se insertan con `AsignadoPor` del token.
4. El último ADMIN activo no puede perder el rol ADMIN → 409.

## Flujo

1. Validar roles y regla del último ADMIN.
2. Desactivar los roles quitados e insertar los nuevos en una transacción.
3. Responder 200; los tokens vigentes conservan los roles viejos hasta su renovación (AUT-02).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idUsuario | path | integer | Sí |  |

Body `RolesUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| roles | string[] | Sí | ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR |

```json
{
  "roles": [
    "CAJERO"
  ]
}
```

## Response `200`

`Usuario`

```json
{
  "idUsuario": 1,
  "username": "mlopez",
  "nombre": "María López",
  "email": "maria.lopez@correo.ec",
  "roles": [
    "CAJERO"
  ],
  "estado": "Activo",
  "fechaCreacion": "2026-11-04T10:15:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
