---
number: 110
title: "AUT-01 | POST /api/v1/auth/login"
type: api
code: AUT-01
parent: "[[F-03 Autenticación y roles]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/110
---

`POST /api/v1/auth/login` · **Roles:** Público · **Historia:** F-03 (#17) · **OpenAPI:** `AUT01`

Valida usuario y contraseña y devuelve access token, refresh token y datos de la sesión.

| Lee | Escribe | DB |
|---|---|---|
| `Organizacion.Usuarios`, `Seguridad.GruposUsuarios`, `Seguridad.Grupos`, `Caja.CajerosAsignadosAgencia` | `Seguridad.Sesiones`, `Usuarios.IntentosFallidos/UltimoAcceso/UltimaSesionID`, `Seguridad.Bloqueos` | SeguridadDB |

## Reglas de negocio

1. Usuario con `Estado` distinto de `Activo` → `423 USUARIO_BLOQUEADO` (Bloqueado) o `401 CREDENCIALES_INVALIDAS` (Inactivo).
2. La contraseña se compara contra `ClaveHash`; el error no dice si falló el usuario o la contraseña → `401 CREDENCIALES_INVALIDAS`.
3. Cada fallo suma `IntentosFallidos`; al llegar a N el usuario pasa a `Bloqueado` y se inserta en `Seguridad.Bloqueos` → `423 USUARIO_BLOQUEADO`.
4. Login correcto reinicia `IntentosFallidos` y actualiza `UltimoAcceso`.
5. Access token: 15 min (`expiresIn = 900`), con `sub`, `roles[]` e `idAgencia`. Refresh token: 8 h.
6. `idAgencia` = asignación vigente (`FechaFin IS NULL` y `Estado = 1`); si no hay, `null`.

## Flujo

1. Buscar usuario por `NombreUsuario` y validar estado.
2. Verificar contraseña; si falla, aplicar regla 3.
3. Cargar roles y agencia vigente.
4. Crear `Seguridad.Sesiones`, generar tokens y responder 200.

## Request

```json
{ "username": "mlopez", "password": "Cajero2026*" }
```

## Response `200`

```json
{
  "accessToken": "<access-token-jwt>",
  "refreshToken": "<refresh-token>",
  "expiresIn": 900,
  "usuario": { "idUsuario": 12, "nombre": "María López", "roles": ["CAJERO"], "idAgencia": "001" }
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400:

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `CREDENCIALES_INVALIDAS` | Usuario inexistente, inactivo o contraseña incorrecta |
| 423 | `USUARIO_BLOQUEADO` | Usuario bloqueado o recién bloqueado por intentos |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] La contraseña nunca aparece en logs

## Pendiente

- Dónde se guarda el refresh token (no hay columna en `Seguridad.Sesiones`) y valor de N (propuesta: 3).
