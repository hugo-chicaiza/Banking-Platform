---
number: 9
title: "T-04 | Depósito en ATM"
type: task
code: T-04
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P3
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/9
---

> Como **cliente**, quiero **depositar efectivo en el ATM** para **no ir a ventanilla**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Cuentas.Cuenta`, `ATM.CuadreATM`

## Criterios de aceptación

- [ ] No se implementa hasta decidir la brecha G-08 (ATM-04)
- [ ] Si se aprueba: modelar el casete de depósito y su cuadre antes de programar

## Dependencias

- Requiere: decisión G-08

## Pendiente

- G-08: la DB no tiene casete de depósito. Los depósitos en efectivo se hacen en ventanilla (CJ-07). Si no se modela, cerrar esta historia.
