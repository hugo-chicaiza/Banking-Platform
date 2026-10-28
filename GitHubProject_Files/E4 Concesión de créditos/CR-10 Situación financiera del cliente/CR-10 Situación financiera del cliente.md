---
number: 68
title: "CR-10 | Situación financiera del cliente"
type: task
code: CR-10
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/68
---

> Como **asesor**, quiero **registrar la situación financiera vigente del cliente** para **calcular su capacidad de pago**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Credito.SituacionFinanciera`

## Criterios de aceptación

- [ ] Registrar ingresos, gastos y deudas; la nueva reemplaza a la vigente (CRE-03)
- [ ] Consultar la vigente (CRE-04)
- [ ] Capacidad de pago = ingresos − gastos − cuota de deuda externa
- [ ] Pruebas: registro, reemplazo, cliente sin situación, montos negativos

## Reglas de negocio

- Es obligatoria para crear la solicitud.

## Dependencias

- Requiere: C-01
- Bloquea: CR-01
