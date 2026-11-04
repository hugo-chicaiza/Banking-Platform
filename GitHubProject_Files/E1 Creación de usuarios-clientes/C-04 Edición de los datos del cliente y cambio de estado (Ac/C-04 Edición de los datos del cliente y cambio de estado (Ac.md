---
number: 47
title: "C-04 | Edición y estado del cliente con auditoría"
type: task
code: C-04
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P2
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/47
---

> Como **asesor**, quiero **editar los datos del cliente y cambiar su estado** para **mantener su información al día con trazabilidad por campo**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Clientes.Cliente`, `Clientes.ClientesHis`

## Criterios de aceptación

- [ ] Se editan los datos permitidos; identificación y tipo de cliente no se modifican
- [ ] Cambio de estado según las transiciones permitidas (CLI-06), con motivo
- [ ] Eliminado es baja lógica
- [ ] Cada campo modificado deja una fila en `ClientesHis` con usuario, fecha e IP
- [ ] Supervisor y auditor consultan el historial de cambios (CLI-07)
- [ ] Pruebas: edición, campo protegido, transición inválida, cliente con productos, historial

## Reglas de negocio

- Transiciones: Activo ⇄ Inactivo · Activo → Suspendido → Activo · Activo → Bloqueado → Activo (ASESOR, SUPERVISOR, ADMIN; aclaración del solicitante del 2026-11-04) · cualquier estado no eliminado → Eliminado.
- `ClientesHis` es inmutable (error DB 57001).

## Dependencias

- Requiere: C-01, C-03

## Decisiones confirmadas el 2026-11-04

- No inactivar ni eliminar si hay cuentas Activa/Bloqueada o cualquier cuenta con Saldo > 0 o SaldoRetenido > 0, ni crédito desembolsado con deuda pendiente. No se deduce la deuda del estado de la solicitud. Si no se puede comprobar, se rechaza el cambio informando la brecha.
- Auditoría anterior/nuevo/motivo en JSON versionado en Observaciones VARCHAR(500), con rechazo si no cabe; sin migración.
- Vínculo WorkOS → usuario entero mediante mapa administrado en configuración del servidor. Ausencia de vínculo impide escribir.
