# SEG-01..10 · Permisos, roles y pestañas por rol

Módulo `app/modules/seguridad`. Todo lo administra **ADMIN**; `GET /seguridad/pestanas` lo lee cualquier usuario con
sesión (el menú de cada uno lo necesita).

## Permisos de los roles (WorkOS)

| Id | Ruta | Qué hace |
|---|---|---|
| SEG01 | GET `/seguridad/permisos` | Catálogo de permisos de WorkOS. Los de sistema (`widgets:*`) van marcados (`sistema`) y al final. |
| SEG09 | POST `/seguridad/permisos` `{slug, nombre, descripcion}` | Crea un permiso general. Slug `<área>-<acción>` (`prd-aprobar`, `con-cerrar`); 409 `PERMISO_DUPLICADO`. |
| SEG10 | DELETE `/seguridad/permisos/{slug}` | Borra el permiso y WorkOS lo quita de los roles. 409 `PERMISO_EN_USO` si la aplicación lo exige (`core/security/permisos.py`). |
| SEG02 | PATCH `/seguridad/permisos/{slug}` | Cambia `nombre` o `descripcion`. El slug no cambia; los de sistema no se editan (409). |
| SEG03 | GET `/seguridad/roles` | Los 7 roles del sistema (`org-*`) con sus permisos. `admin`/`member` de entorno no se listan. |
| SEG04 | POST `/seguridad/roles/{rol}/permisos` `{permiso}` | Asigna un permiso. Si ya lo tiene, no llama a WorkOS. |
| SEG05 | DELETE `/seguridad/roles/{rol}/permisos/{permiso}` | Quita un permiso; 404 `PERMISO_NO_ASIGNADO` si no lo tiene. |
| SEG06 | PUT `/seguridad/roles/{rol}/permisos` `{permisos[]}` | Deja exactamente esos permisos; los de sistema que ya tenga se conservan. |

- `rol` es el rol del sistema en mayúsculas (`CONTADOR`); se traduce a `org-contador`.
- Solo se asignan permisos que existen y no son de sistema: 404 `PERMISO_NO_ENCONTRADO`, 409 `PERMISO_DE_SISTEMA`.
- **Un permiso nuevo no habilita nada por sí solo:** sirve cuando el código lo exige (`require_permiso` y
  `core/security/permisos.py`). Hasta entonces asignarlo a un rol no cambia el acceso.
- Un cambio aplica en la siguiente sesión o refresco de cada usuario (cuando WorkOS emite el token nuevo).
- Errores de WorkOS: caído → 503 `WORKOS_NO_DISPONIBLE`; rechazo → 422 `WORKOS_RECHAZO`.
- Auditoría: `CREAR_PERMISO`, `BORRAR_PERMISO`, `ASIGNAR_PERMISO_ROL`, `QUITAR_PERMISO_ROL`, `REEMPLAZAR_PERMISOS_ROL` (`WorkOS.Roles`) y
  `EDITAR_PERMISO` (`WorkOS.Permisos`), con éxito o fallo.

## Pestañas por rol (SeguridadDB)

| Id | Ruta | Qué hace |
|---|---|---|
| SEG07 | GET `/seguridad/pestanas` | `[{pestana, roles[]}]` de las pestañas personalizadas. Las que no aparecen usan el menú por defecto. |
| SEG08 | PUT `/seguridad/pestanas` `{pestanas: [{pestana, roles[]}]}` | Reemplaza toda la configuración. Lista vacía = menú por defecto. |

- `pestana` es la ruta del frontend (`/cuentas/abrir`): minúsculas, dígitos, `/` y `-`, hasta 80 caracteres.
- `/`, `/seguridad/roles` y `/seguridad/pestanas` **no se configuran** (422 `PESTANA_NO_CONFIGURABLE`): así un ADMIN
  no puede quitarse el acceso a esta configuración.
- **Solo decide qué muestra el menú.** Cada API sigue validando rol o permiso: mostrar una pestaña a un rol que la API
  no admite solo hace que esa pantalla responda 403.
- Tabla `Seguridad.PestanaRol` (migración `migrations/20261118_seguridad_pestana_rol.tsql`, ejecutar antes de
  desplegar). Sin la tabla, el frontend usa el menú por defecto.
- Auditoría: `CONFIGURAR_PESTANAS` (`Seguridad.PestanaRol`).
