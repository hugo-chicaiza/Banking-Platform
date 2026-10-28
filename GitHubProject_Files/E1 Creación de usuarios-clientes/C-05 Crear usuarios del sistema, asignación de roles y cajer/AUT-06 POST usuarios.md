---
number: 190
title: "AUT-06 | POST /api/v1/usuarios"
type: api
code: AUT-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/190
---

`POST /api/v1/usuarios` · **Roles:** ADMIN · **Historia:** C-05 (#48) · **OpenAPI:** `AUT06`

Crea un usuario del sistema.

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.Grupos` | `Organizacion.Usuarios`, `Seguridad.GruposUsuarios` | — |

## Reglas de negocio

1. `NombreUsuario`, `Email` y `Cedula` (10 dígitos) son únicos → `409 USUARIO_DUPLICADO`.
2. `passwordTemporal` se guarda solo como hash en `ClaveHash`; el usuario la cambia en su primer ingreso.
3. Todos los `roles` deben existir y estar `Activo` en `Seguridad.Grupos` → si no, 400.
4. Se crea con `Estado = 'Activo'` e `IntentosFallidos = 0`; `AsignadoPor` sale del token.

## Flujo

1. Validar unicidad y roles.
2. Insertar el usuario y una fila en `GruposUsuarios` por rol, en una transacción.
3. Responder 201 con el usuario (sin hash).

## Request

Body `UsuarioCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| username | string | Sí |  |
| nombre | string | Sí |  |
| email | string | Sí |  |
| passwordTemporal | string | Sí |  |
| roles | string[] | Sí |  |

```json
{
  "username": "mlopez",
  "nombre": "María López",
  "email": "maria.lopez@correo.ec",
  "passwordTemporal": "Temporal2026*",
  "roles": [
    "CAJERO"
  ]
}
```

## Response `201`

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

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `USUARIO_DUPLICADO` | Ya existe el `username`, el email o la cédula |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- Contrato dice `Seguridad.Usuario/UsuarioRol`; la DB usa `Organizacion.Usuarios` y `Seguridad.GruposUsuarios`. `UsuarioCreate` no trae `cedula`, que la DB exige: agregarla al contrato.
