---
number: 69
title: "CR-11 | Consulta de buró de crédito"
type: task
code: CR-11
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: S
estimate: 2
estimate_be: 2
estimate_fe: 0
etapa: "3-4"
start_date: 2026-11-04
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/69
---

> Como **sistema**, quiero **consultar el buró con el consentimiento del titular** para **usar su score en la evaluación**.

**Etapa:** 3-4 · **QA:** 0 d · **Tablas:** `Credito.ReporteBuro`

## Criterios de aceptación

- [ ] Sin consentimiento no se consulta (CRE-05)
- [ ] El reporte (score y resumen) queda guardado y lo usa la solicitud
- [ ] Si el buró no responde, la solicitud pasa a revisión manual
- [ ] Pruebas: consulta correcta, sin consentimiento, buró caído

## Reglas de negocio

- La integración es simulada.

## Dependencias

- Bloquea: CR-01, CR-02
