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
- `KeyUsuario` se llena en el primer login (email verificado por WorkOS). Sin él, la API responde `403 USUARIO_NO_REGISTRADO`.
- La agencia del usuario es `AgenciaID` (F-03) y la del cajero habilita su jornada de caja (CJ-01).
- El primer ADMIN se registra a mano: miembro de EnquoCoop con `org-admin` y su fila en `Organizacion.Usuarios` con `KeyUsuario`.

## Dependencias

- Requiere: F-03, F-04, F-08
- Bloquea: CJ-01

## Pendiente

- Actualizar `openapi.yaml` al contrato de AUT-05..09 (un `rol`, `cedula`, `idAgencia`, sin `passwordTemporal`).
- AUT-10 y AUT-11 (asignación de cajeros).
