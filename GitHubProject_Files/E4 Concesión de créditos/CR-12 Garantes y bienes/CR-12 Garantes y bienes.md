---
number: 70
title: "CR-12 | Garantes y bienes"
type: task
code: CR-12
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P2
size: M
estimate: 4
estimate_be: 2
estimate_fe: 2
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/70
---

> Como **asesor**, quiero **registrar garantes con sus bienes y vincularlos a la solicitud** para **respaldar el crédito**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Credito.Garante`, `Credito.GaranteBien`, `Credito.CreditoGarante`

## Criterios de aceptación

- [ ] Registrar y buscar garantes (CRE-20, CRE-21)
- [ ] Registrar bienes; un inmueble exige datos de escritura (CRE-22)
- [ ] Vincular garantes a la solicitud sin duplicar (CRE-23)
- [ ] El garante nunca es el propio solicitante
- [ ] Pruebas: garante duplicado, garante = solicitante, inmueble sin escritura, doble vínculo

## Dependencias

- Requiere: CR-01
