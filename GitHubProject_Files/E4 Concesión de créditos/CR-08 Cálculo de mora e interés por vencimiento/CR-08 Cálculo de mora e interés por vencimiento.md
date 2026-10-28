---
number: 36
title: "CR-08 | Cálculo diario de mora"
type: task
code: CR-08
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P2
size: S
estimate: 2
estimate_be: 2
estimate_fe: 0
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/36
---

> Como **sistema**, quiero **marcar cuotas vencidas y calcular su mora cada día** para **cobrar el recargo correcto**.

**Etapa:** 4-5 · **QA:** 0 d · **Tablas:** `Credito.CreditoCuotaMora`, `Credito.CreditoCuota`, `Credito.TasaInteres`

## Criterios de aceptación

- [ ] Proceso diario que no se ejecuta dos veces para la misma fecha (CRE-19)
- [ ] Cuotas PENDIENTE vencidas pasan a VENCIDA con su registro de mora
- [ ] Ver la mora del crédito (CRE-18)
- [ ] Pruebas: cuota a tiempo, 1 día de mora, varios días, ejecución repetida

## Reglas de negocio

- Tasa de mora = `TasaNominalAnual + RecargoMoraSobreTasa`, sobre el capital vencido por días.

## Dependencias

- Requiere: CR-05
