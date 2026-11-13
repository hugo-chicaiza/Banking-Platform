# Plan · Gestión de permisos, roles y grupos con WorkOS (extensión de C-05)

## Contexto
El ADMIN necesita administrar desde la UI, vía API de WorkOS:
1. Permisos (CRUD).
2. La membresía de un usuario en EnquoCoop (`WORKOS_ORGANIZATION_ID`): verla y crearla.
3. Grupos de usuarios en EnquoCoop (CRUD + ver/agregar/quitar miembros).
4. Rol de un grupo.
5. Roles de la organización (CRUD) y sus permisos (ver/agregar/quitar/reemplazar).

Decisiones del usuario:
- Roles fijos + permisos: los 7 roles del sistema siguen dando el acceso a la API y no se pueden borrar. Pasar las rutas a `require_permiso` es una fase aparte (fuera de este plan).
- Actualizar el SDK de WorkOS a la última versión.

### Respuestas a las dudas
- **¿Se puede dejar al usuario sin rol directo y solo con el del grupo?** No. La documentación de WorkOS dice: *"Each organization membership must have at least one role… they will always receive the default role if no other role(s) are set"* (multiple-roles). Lo que sí se puede, en modo **un solo rol** (el que tenemos, sin activar Multiple Roles): *"Group role assignments work in both single-role and multiple-role modes"* y *"the highest-priority role across direct and group sources wins"*. O sea:
  - el rol directo queda en el rol por defecto (`member`, sin permisos y con la prioridad más baja);
  - el rol del grupo, que tiene más prioridad, es el que va en el token (`role`), y el usuario termina con **un solo rol efectivo**.
  - Si el rol directo tiene más prioridad que el del grupo, gana el directo.
  - Si se quita el rol del grupo, el usuario vuelve al rol por defecto.
- **¿Por qué 5.46.0?** No lo elegí yo. `Backend/requirements.in` tiene `workos>=5.0,<6.0` desde `319d22b` (Matthew, 29-10, `fix(ci): …SonarCloud…`), y el lock resolvió 5.46.0. La última versión es la 10.9.0 (publicada el 13-11).

### Qué permite la API de WorkOS (verificado en la documentación)
| Necesidad | API | Notas |
|---|---|---|
| Permisos | `POST/GET/PATCH/DELETE /authorization/permissions[/{slug}]` | `slug` inmutable; solo cambian `name` y `description`. Los permisos de sistema no se borran. |
| Roles de EnquoCoop | `…/authorization/organizations/{org}/roles[/{slug}]`: crear, listar, ver, editar, **borrar** | El slug debe empezar con `org-` y es inmutable. Al borrar un rol asignado: `409 role_has_assignments` / `role_has_group_role_mappings`. El listado incluye los roles de entorno. |
| Permisos de un rol | `POST` (agregar), `DELETE …/permissions/{perm}` (quitar), `PUT` (reemplazar) | — |
| Membresía | `create/list/get/update/deactivate/reactivate/delete` | El listado filtra por `user_id` + `organization_id` + `statuses`. |
| Grupos | `POST/GET/PATCH/DELETE /organizations/{org}/groups[/{id}]`; miembros: `GET/POST/DELETE …/organization-memberships[/{omId}]` | Grupos nativos de AuthKit, no de Directory Sync. Agregar o quitar un miembro aplica su rol al instante. |
| Rol de un grupo | `/authorization/groups/{id}/role_assignments`: crear, listar, borrar, reemplazar (`PUT`) | Cambiar el rol de un grupo se aplica a sus miembros en segundo plano, con un breve retraso. |
| **No existe** | Borrar o quitar permisos de **roles de entorno**; activar Multiple Roles; definir el rol por defecto | Se hace solo en el Dashboard. |

## Fase 0 · Actualizar el SDK a 10.9.0 (commit propio)
- `Backend/requirements.in`: `workos>=10.9,<11`; regenerar `requirements.txt` y `requirements-dev.txt` con el comando `uv pip compile` de la cabecera.
- Cambios mayores 6→10 que nos afectan:
  - Las membresías salen de `user_management` y pasan a `client.organization_membership` (8.0).
  - `RoleSingle`/`RoleMultiple` eliminados (8.0).
  - `return_to` eliminado de `RevokeSession` (8.1).
  - Iterar un listado ya no recorre todas las páginas (10.6).
- Antes de tocar código, verificar con el SDK instalado (no con la documentación, que no lo cubre) los nombres de: `authenticate_with_code`, `load_sealed_session`, `get_authorization_url`, `get_logout_url`, invitaciones, `list_users`, `update_user`, sesiones y grupos.
- Archivos a adaptar:
  - `app/integrations/workos_client.py`
  - `app/core/security/auth.py`: `load_sealed_session`, tipos de sesión.
  - `app/modules/auth/service.py`: unas 19 llamadas e imports de tipos.
  - Fakes de `tests/unit/test_auth.py`, `tests/unit/test_usuarios.py`, `tests/sesion.py`.
- Criterio: las pruebas actuales pasan sin cambiar su comportamiento. Si 10.x quitó la sesión sellada, se para y se consulta antes de seguir.

## Fase 1 · Endpoints (todos `require_roles("ADMIN")`, prefijo `/api/v1`)
Mismo módulo `app/modules/auth/`:
- Routers nuevos `/permisos`, `/roles` y `/grupos`, con lógica en un `service_autorizacion.py` nuevo.
- Reutilizar `_workos` (`auth/service.py`), ampliado para traducir los errores de WorkOS:
  - 404 → `404 NO_ENCONTRADO`;
  - 409 → `409` con el código de WorkOS;
  - rechazo → `422 WORKOS_RECHAZO`;
  - caída → `503`.
- Reutilizar también `auditar`/`audit.registrar`, con `TablaAfectada` `WorkOS.Permisos`, `WorkOS.Roles` o `WorkOS.Grupos`.
- Reutilizar `CamelModel`, `problema`, `solo_parametros`, `ProblemDetailsRoute`, `RESPUESTAS_ERROR`, `get_organizacion_id()` y `slug_rol`/`ROLES`/`Rol` (`core/security/auth.py`).

| # | Endpoint | Regla |
|---|---|---|
| 1 | `GET /permisos` (cursor `after`, `limit≤100`), `GET/PATCH/DELETE /permisos/{slug}`, `POST /permisos` | Slug con el formato de WorkOS (`[a-z0-9_.:*-]`). El PATCH solo acepta `nombre` y `descripcion`. |
| 2 | `GET /usuarios/{id}/membresia` | `{miembro, estado, rol, idMembresia}`, todos los estados. Busca el usuario de WorkOS por `KeyUsuario` o por email (`_usuario_workos`). |
| 2 | `POST /usuarios/{id}/membresia` | Crea la membresía en EnquoCoop con el rol de `RolesWorkOS`. Si ya es miembro, 409 `YA_ES_MIEMBRO`. Si no existe en WorkOS, 409 `SIN_USUARIO_WORKOS` (hay que invitarlo con AUT-06). Vincula `KeyUsuario` con `_resolver_sin_vinculo`. |
| 3 | `GET/POST /grupos`, `GET/PATCH/DELETE /grupos/{idGrupo}` | Siempre dentro de `WORKOS_ORGANIZATION_ID`. |
| 3 | `GET /grupos/{id}/miembros`, `POST /grupos/{id}/miembros` `{idUsuario}`, `DELETE /grupos/{id}/miembros/{idUsuario}` | Traduce `idUsuario` → `KeyUsuario` → id de membresía. El listado se completa con username y nombres de `Organizacion.Usuarios`. |
| 4 | `GET /grupos/{id}/rol`, `PUT /grupos/{id}/rol` `{rol}`, `DELETE /grupos/{id}/rol` | Un rol por grupo: el `PUT` reemplaza todas las asignaciones. Solo acepta roles que existan en EnquoCoop. |
| 5 | `GET/POST /roles`, `GET/PATCH/DELETE /roles/{slug}` | Slug `org-[a-z0-9-]+`. Los 7 roles del sistema (`slug_rol(r) for r in ROLES`) no se borran (409 `ROL_DEL_SISTEMA`), pero sí se editan su nombre, descripción y permisos. Un rol asignado da 409 con el código de WorkOS. |
| 5 | `GET /roles/{slug}/permisos`, `POST /roles/{slug}/permisos` `{slug}`, `DELETE /roles/{slug}/permisos/{permiso}`, `PUT /roles/{slug}/permisos` `{permisos[]}` | — |

Efectos sobre lo existente:
- **Último ADMIN** (`_hay_otro_admin`): hoy cuenta las membresías con `role.slug == org-admin`. Si el rol de la membresía no refleja el que viene del grupo (la documentación no lo aclara), hay que contar también a los miembros de grupos con `org-admin`. Lo mismo aplica antes de quitar un miembro o el rol de un grupo con `org-admin`. Se confirma en Staging.
- `RolesWorkOS` ya se reescribe en cada login con el rol del token (`_id_interno_db`), así que refleja el rol efectivo.
- Un rol nuevo (no del sistema) que llegue en el token se ignora en la API (`normalizar_roles`) hasta la fase de permisos.

## Configuración en WorkOS (Dashboard, sin API)
- Rol por defecto `member`, sin permisos y con la prioridad más baja. Prioridad de los roles del sistema, de mayor a menor: ADMIN > SUPERVISOR > … (define cuál gana entre el rol directo y el del grupo).
- Multiple Roles **apagado**.

## Documentación
- Nuevos `AUT-12 Permisos`, `AUT-13 Membresía`, `AUT-14 Grupos`, `AUT-15 Rol de grupo` y `AUT-16 Roles y permisos` en la carpeta de C-05, con el formato de AUT-05..09.
- C-05: modelo de rol efectivo (directo frente a grupo) y configuración en WorkOS.
- `.env.example`: versión del SDK.

## Verificación
- `ruff check/format`, `pyright --pythonpath`, `bandit` y la suite completa de `pytest` después de la Fase 0 y de la Fase 1.
- Pruebas unitarias con WorkOS simulado para cada endpoint:
  - borrar un rol del sistema → 409;
  - borrar un rol asignado → 409;
  - membresía duplicada → 409;
  - usuario sin WorkOS → 409;
  - miembro de grupo mapeado a `idUsuario`;
  - WorkOS caído → 503;
  - auditoría de cada escritura.
- `ROLES_POR_RUTA` en `tests/unit/test_autorizacion.py` con todas las rutas nuevas como `("ADMIN",)`.
- En WorkOS Staging, en local:
  1. crear permiso → crear rol `org-prueba` → asignarle el permiso;
  2. crear grupo → agregar al usuario 29 → `PUT /grupos/{id}/rol` → volver a hacer login y confirmar en `/auth/me` el rol efectivo;
  3. confirmar qué devuelve la membresía (`role`) para decidir la regla del último ADMIN;
  4. quitar del grupo → vuelve a `member`.
