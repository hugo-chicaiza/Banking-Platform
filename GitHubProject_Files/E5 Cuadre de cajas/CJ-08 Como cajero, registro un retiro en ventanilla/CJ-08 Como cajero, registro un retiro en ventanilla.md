---
number: 61
title: "CJ-08 | Retiro en ventanilla"
type: task
code: CJ-08
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/61
---

> Como **cajero**, quiero **registrar un retiro en ventanilla** para **entregar efectivo al cliente**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Cuentas.Cuenta`, `Caja.MovimientosCaja`

## Criterios de aceptación

- [ ] Se valida saldo disponible, cupos y efectivo de la caja (CAJ-11)
- [ ] Transacción, débito, movimiento de caja y asiento quedan juntos
- [ ] Pruebas: retiro correcto, fondos insuficientes, caja sin efectivo, sin jornada, reintento idempotente

## Dependencias

- Requiere: CJ-01, CJ-02, T-08, AC-01
