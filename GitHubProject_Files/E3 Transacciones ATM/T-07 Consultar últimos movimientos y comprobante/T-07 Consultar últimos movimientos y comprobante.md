---
number: 12
title: "T-07 | Últimos movimientos y comprobante en ATM"
type: task
code: T-07
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P3
size: S
estimate: 2
estimate_be: 1
estimate_fe: 1
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/12
---

> Como **cliente**, quiero **ver mis últimos movimientos en el ATM** para **revisar mi cuenta al momento**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Cuentas.MovimientoTransaccion`, `Transacciones.Transaccion`

## Criterios de aceptación

- [ ] Muestra los últimos 10 movimientos de una cuenta de la sesión (ATM-07)
- [ ] Cada operación de ATM entrega comprobante con número, monto, comisión y saldo
- [ ] Pruebas: cuenta con y sin movimientos, cuenta ajena

## Dependencias

- Requiere: T-01
