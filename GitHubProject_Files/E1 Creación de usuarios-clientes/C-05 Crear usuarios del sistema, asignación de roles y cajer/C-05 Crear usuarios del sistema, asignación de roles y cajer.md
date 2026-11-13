---
number: 48
title: "C-05 | Usuarios del sistema, roles y cajeros por agencia"
type: task
code: C-05
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/48
---

> Como **administrador**, quiero **crear usuarios, asignarles roles y asignar cajeros a agencias** para **controlar quién opera cada módulo y en qué agencia**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Organizacion.Usuarios`, `Seguridad.Bloqueos` (SeguridadDB) · `Caja.CajerosAsignadosAgencia` · **Externo:** WorkOS (organización EnquoCoop)

## Criterios de aceptación

- [x] Listar, crear, ver y editar usuarios (AUT-05 a AUT-08)
- [x] Usuario, email y cédula no se repiten; la contraseña la define el usuario en WorkOS (invitación), nunca pasa por el backend
- [x] Reemplazar el rol de un usuario con un rol válido (AUT-09)
- [ ] Ver el historial de cajeros de una agencia y asignar un cajero (AUT-10, AUT-11)
- [ ] Un cajero tiene una sola asignación vigente
- [x] Pruebas AUT-05..09: alta, duplicados, bloqueo y desbloqueo, roles inválidos, último ADMIN
- [ ] Probado contra WorkOS Staging

## Reglas de negocio

- Una sola organización en WorkOS (EnquoCoop, `WORKOS_ORGANIZATION_ID`); todos los usuarios internos son miembros.
- **Un rol por usuario**: ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR. Vive en la membresía de WorkOS con slug `org-<rol>` y se copia en `Organizacion.Usuarios.RolesWorkOS`. No se usan `Seguridad.Grupos` ni `Seguridad.GruposUsuarios`.
- La base es la fuente del usuario interno: datos, estado, agencia (`AgenciaID`) y bloqueos.
- `KeyUsuario` se llena en el primer login (email verificado por WorkOS) o, si el login no lo vinculó, en AUT-08/09 cuando el email ya es miembro de EnquoCoop y está verificado. Sin él, la API responde `403 USUARIO_NO_REGISTRADO`.
- Se reinvita solo si el email no existe en WorkOS. Un usuario de WorkOS sin membresía en EnquoCoop responde 409.
- La agencia del usuario es `AgenciaID` (F-03) y la del cajero habilita su jornada de caja (CJ-01).
- **Lectura de roles:** el prefijo `org-` es opcional y los guiones equivalen a `_` (`org-cajero`, `cajero` y `CAJERO` dan CAJERO). Se ignoran los slugs que no son roles del sistema (`member`) y las sesiones de otra organización (quedan sin roles).
- **Escritura de roles:** AUT-06 y AUT-09 siempre escriben `org-<rol>`. La regla del último ADMIN solo cuenta membresías `org-admin`: un `admin` sin prefijo no cuenta (falla cerrado).

## Configuración

1. `WORKOS_ORGANIZATION_ID` (id `org_…` de EnquoCoop): primero en `.env` local; en Azure después de verificarlo localmente.
2. Roles `org-*` creados en WorkOS. La membresía nueva toma el rol de la invitación.
3. **Initiate login URI** por entorno (`<frontend>/api/v1/auth/login`): AuthKit manda ahí al usuario que llega desde la invitación, la verificación o el reset para que el login genere su `state`.
4. **Primer ADMIN** a mano: miembro de EnquoCoop con `org-admin` y su fila en `Organizacion.Usuarios` (`Estado = 'Activo'`, `RolesWorkOS = 'ADMIN'`). Para probar el vínculo del primer login, dejar `KeyUsuario = NULL` con el mismo email verificado: el login lo llena. Sin esa fila ningún ADMIN entra y no se pueden crear usuarios.

## Prueba local (WorkOS Staging)

1. Login del primer ADMIN → `KeyUsuario` y `UltimoAcceso` llenos; `/auth/me` con rol ADMIN.
2. AUT-06 → invitación → aceptarla → login → `vinculado = true`.
3. AUT-09 cambia el rol; AUT-08 bloquea → la sesión del usuario cae y queda el registro en `Seguridad.Bloqueos`.

## Dependencias

- Requiere: F-03, F-04, F-08
- Bloquea: CJ-01

## Pendiente

- Probar el flujo local contra WorkOS Staging y luego pasar `WORKOS_ORGANIZATION_ID` a Azure.
- AUT-10 y AUT-11 (asignación de cajeros).
