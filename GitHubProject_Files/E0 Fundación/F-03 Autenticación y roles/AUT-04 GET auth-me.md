---
number: 113
title: "AUT-04 | GET /api/v1/auth/me"
type: api
code: AUT-04
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/113
---

`GET /api/v1/auth/me` · **Roles:** Cookie de sesión · **Historia:** F-03 (#17) · **OpenAPI:** `AUT04`

Devuelve el usuario de la sesión, sus roles, permisos y agencia vigente. El FE lo usa al cargar para saber si hay sesión y para el menú y las rutas (F-05).

| Lee | Escribe | Externo |
|---|---|---|
| Cookie `__Host-session` | Cookie si se renovó | WorkOS (JWKS; refresh si venció) |

## Reglas de negocio

1. El usuario sale de la sesión, nunca de un parámetro.
2. Si el access token venció, se renueva y se reescribe la cookie antes de responder.
3. `roles`: claims `roles`/`role` de WorkOS normalizados (`aprobador-credito` → `APROBADOR_CREDITO`); se ignoran los que no son del sistema (ej. `member`). Lista: un usuario puede tener varios.
4. `idAgencia`: metadato `idAgencia` del usuario en WorkOS (3 dígitos); si no hay, `null`.
5. `permisos`: claim `permissions` de WorkOS tal cual.

## Response `200`

```json
{
  "idUsuario": "user_01J...",
  "nombre": "María López",
  "email": "maria.lopez@correo.ec",
  "idOrganizacion": "org_01J...",
  "roles": ["CAJERO"],
  "permisos": [],
  "idAgencia": "001"
}
```

## Errores

Formato ProblemDetails (ver F-04).

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `NO_AUTENTICADO` | Sin sesión o sesión que no se pudo renovar (se borra la cookie); el FE va a `/auth/login` |
| 403 | `USUARIO_NO_REGISTRADO` | La sesión es válida, pero el usuario no está vinculado o no está `Activo` (por ejemplo, se bloqueó con la sesión abierta) |
| 503 | `AUTENTICACION_NO_DISPONIBLE` | No se pudieron descargar las llaves de WorkOS |

## Definición de terminado

- [x] Un rol, varios roles, sin agencia, token vencido renovado, sin cookie, cookie inválida (`tests/unit/test_auth.py`)
