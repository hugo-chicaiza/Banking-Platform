---
number: 35
title: "CR-07 | Estado del crédito, plan y cuotas"
type: task
code: CR-07
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P2
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/35
---

> Como **asesor o cajero**, quiero **ver el estado del crédito, su plan y sus cuotas** para **informar al cliente cuánto debe y cuándo**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Credito.CreditoResumen`, `Credito.CreditoCuota`, `Credito.CreditoPlanAmortizacion`

## Criterios de aceptación

- [ ] Resumen con estado derivado (VIGENTE, EN_MORA, CANCELADO…), saldo y próxima cuota (CRE-13)
- [ ] Plan vigente o de una versión anterior (CRE-14)
- [ ] Cuotas con estado, mora y total a pagar (CRE-15)
- [ ] Pruebas: crédito al día, en mora, cancelado y refinanciado

## Dependencias

- Requiere: CR-05

## Pendiente

- G-05 (aplicar): vista `Credito.vw_EstadoCredito`.
