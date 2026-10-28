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

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Organizacion.Usuarios`, `Seguridad.Grupos`, `Seguridad.GruposUsuarios`, `Seguridad.Bloqueos` (SeguridadDB) · `Caja.CajerosAsignadosAgencia`

## Criterios de aceptación

- [ ] Listar, crear, ver y editar usuarios (AUT-05 a AUT-08)
- [ ] Usuario, email y cédula no se repiten; la contraseña se guarda solo como hash
- [ ] Reemplazar los roles de un usuario con roles válidos (AUT-09)
- [ ] Ver el historial de cajeros de una agencia y asignar un cajero (AUT-10, AUT-11)
- [ ] Un cajero tiene una sola asignación vigente
- [ ] Pruebas: alta, duplicados, bloqueo y desbloqueo, roles inválidos, último ADMIN, asignación duplicada

## Reglas de negocio

- Roles: ADMIN, ASESOR, CAJERO, SUPERVISOR, APROBADOR_CREDITO, CONTADOR, AUDITOR.
- La agencia vigente del cajero es la que va en el JWT (F-03) y la que habilita su jornada de caja (CJ-01).

## Dependencias

- Requiere: F-03, F-04, F-08
- Bloquea: CJ-01

## Pendiente

- El contrato usa `Seguridad.Usuario/UsuarioRol`; actualizar `openapi.yaml` a las tablas de SeguridadDB y agregar `cedula` a `UsuarioCreate`.
