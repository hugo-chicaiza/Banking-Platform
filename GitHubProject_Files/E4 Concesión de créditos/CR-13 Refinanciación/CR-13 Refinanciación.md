---
number: 71
title: "CR-13 | Refinanciación"
type: task
code: CR-13
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P3
size: M
estimate: 4
estimate_be: 3
estimate_fe: 1
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/71
---

> Como **supervisor**, quiero **refinanciar un crédito vigente con un nuevo plan** para **ajustar los pagos del cliente**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Credito.CreditoRefinanciacion`, `Credito.CreditoPlanAmortizacion`, `Credito.CreditoCuota`, `Credito.CreditoResumen`

## Criterios de aceptación

- [ ] Nueva versión del plan con motivo; la anterior deja de ser vigente (CRE-24)
- [ ] Las cuotas nuevas salen de la versión vigente
- [ ] Pruebas: refinanciar vigente, crédito cancelado, crédito no desembolsado

## Dependencias

- Requiere: CR-05, CR-07
