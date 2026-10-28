---
number: 59
title: "A-05 | PIN y estados de tarjeta"
type: task
code: A-05
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/59
---

> Como **asesor**, quiero **asignar el PIN y activar, bloquear o desbloquear tarjetas** para **que el cliente use su tarjeta de forma segura**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Tarjeta.Tarjeta`, `Tarjeta.TransicionEstado`, `Tarjeta.TarjetaHis` · `TarjetaPIN` (SeguridadDB)

## Criterios de aceptación

- [ ] Asignar el PIN inicial una sola vez, con hash + salt (TAR-05)
- [ ] Cambiar el estado solo según `Tarjeta.TransicionEstado` (TAR-04); activar exige PIN
- [ ] Ver el historial de eventos de la tarjeta (TAR-06)
- [ ] El PIN nunca aparece en logs, respuestas ni errores
- [ ] Pruebas: PIN débil, PIN ya asignado, transición válida e inválida, activar sin PIN

## Dependencias

- Requiere: A-04, F-08 (G-02)
- Bloquea: T-01, T-06

## Pendiente

- G-02 (aplicar): `SeguridadDB.TarjetaPIN` no tiene columnas de hash ni salt.
