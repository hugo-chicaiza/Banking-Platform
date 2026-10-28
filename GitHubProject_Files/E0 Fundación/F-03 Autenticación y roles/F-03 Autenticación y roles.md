---
number: 17
title: "F-03 | Autenticación y roles"
type: task
code: F-03
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: XL
estimate: 8
estimate_be: 5
estimate_fe: 3
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/17
---

> Como **usuario del sistema**, quiero **iniciar sesión con JWT y tener roles** para **acceder solo a lo que me corresponde**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Organizacion.Usuarios`, `Seguridad.Grupos`, `Seguridad.GruposUsuarios`, `Seguridad.Sesiones`, `Seguridad.Bloqueos` (SeguridadDB) · `Caja.CajerosAsignadosAgencia`

## Criterios de aceptación

- [ ] Login devuelve access token (15 min) y refresh token (AUT-01)
- [ ] Refresh renueva el access token y logout revoca la sesión (AUT-02, AUT-03)
- [ ] `GET /auth/me` devuelve usuario, roles y agencia vigente (AUT-04)
- [ ] Tras N intentos fallidos el usuario queda `Bloqueado` → `423 USUARIO_BLOQUEADO`
- [ ] Sin token → 401; rol sin permiso → 403
- [ ] Roles: ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR
- [ ] FE: pantalla de login con errores y renovación automática del token

## Reglas de negocio

- Contraseñas solo como hash (`ClaveHash`), nunca en texto plano ni en logs.
- El JWT lleva `sub` = IdUsuario, `roles[]` e `idAgencia`; todo `CreadoPor`/`RegistradoPor` sale del token.
- Los roles son los `Seguridad.Grupos` asignados en `GruposUsuarios` con `Estado = 'Activo'`.

## Dependencias

- Requiere: F-08 (decisión G-01)
- Bloquea: F-05, C-05, A-05, T-01, T-06

## Pendiente

- G-01 se descartó porque la autenticación vive en `SeguridadDB`. Falta decidir dónde se guarda el refresh token (`Seguridad.Sesiones` no tiene columna) y N de intentos (propuesta: 3).
