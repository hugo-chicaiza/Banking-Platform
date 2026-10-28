---
number: 37
title: "CR-09 | Pago anticipado o cancelación total"
type: task
code: CR-09
parent: "[[E4 Concesión de créditos]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/37
---

> Como **cliente**, quiero **adelantar pagos o cancelar todo el crédito** para **pagar menos intereses**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Credito.CreditoCuotaPago`, `Credito.CreditoCuota`

## Criterios de aceptación

- [ ] Cotizar la cancelación total a una fecha (CRE-16 con `cancelacionTotal`)
- [ ] Registrar el pago con `EsCancelacionAnticipada` (CRE-17); el crédito queda CANCELADO
- [ ] Pruebas: cancelación total, pago anticipado parcial, crédito con mora

## Dependencias

- Requiere: CR-06
