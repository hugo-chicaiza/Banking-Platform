---
number: 60
title: "CJ-07 | Depósito en ventanilla con series"
type: task
code: CJ-07
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/60
---

> Como **cajero**, quiero **registrar un depósito con su desglose y las series de los billetes de $50 y $100** para **acreditar la cuenta y controlar billetes falsos**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Cuentas.Cuenta`, `Caja.MovimientosCaja`, `Boveda.BilleteSerie`

## Criterios de aceptación

- [ ] El desglose suma el monto; transacción, crédito, movimiento de caja y asiento quedan juntos (CAJ-09)
- [ ] Registrar las series de $50 y $100 sin repetidas y con la cantidad declarada (CAJ-10)
- [ ] Sirve también para el depósito de apertura de cuenta (A-01)
- [ ] Pruebas: depósito correcto, desglose distinto, cuenta cerrada, serie repetida, reintento idempotente

## Dependencias

- Requiere: CJ-01, CJ-02, T-08, AC-01
