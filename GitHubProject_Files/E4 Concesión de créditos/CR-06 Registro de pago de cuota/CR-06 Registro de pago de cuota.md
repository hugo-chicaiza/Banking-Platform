---
number: 34
title: "CR-06 | Pago de cuota"
type: task
code: CR-06
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: L
estimate: 7
estimate_be: 4
estimate_fe: 3
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/34
---

> Como **cajero**, quiero **registrar el pago de una cuota con su mora** para **que el crédito del cliente quede al día**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Credito.CreditoCuotaPago`, `Credito.CreditoCuotaAbono`, `Credito.CreditoCuotaMora`, `Transacciones.Transaccion`, `Caja.MovimientosCaja`

## Criterios de aceptación

- [ ] Cotizar el pago a una fecha (CRE-16) y registrarlo (CRE-17)
- [ ] Se paga en orden; la mora se liquida con el pago
- [ ] Pago completo marca la cuota PAGADA; pago parcial queda como abono a capital
- [ ] En ventanilla exige jornada de caja abierta y genera el movimiento de caja
- [ ] Pruebas: pago exacto, parcial, con mora, cuota fuera de orden, cuota ya pagada, sin jornada

## Dependencias

- Requiere: CR-05, CJ-01, CJ-02

## Pendiente

- G-10 (aplicar): `Transaccion.IdCuenta` es obligatoria; el pago se asocia a la cuenta del cliente.
