---
number: 30
title: "CR-04 | Aprobación o rechazo manual"
type: task
code: CR-04
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/30
---

> Como **aprobador**, quiero **resolver las solicitudes en revisión manual** para **decidir los casos que la política no resuelve sola**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Credito.CreditoSolicitud`, `Credito.CreditoSolicitudHistorialEstado`

## Criterios de aceptación

- [ ] Bandeja de solicitudes en REVISION_MANUAL (CRE-07)
- [ ] Aprobar o rechazar con observación; el aprobador no es quien creó la solicitud (CRE-09)
- [ ] El cliente puede desistir de una solicitud no desembolsada (CRE-10)
- [ ] Ver el historial de estados (CRE-11)
- [ ] Pruebas: aprobar, rechazar, aprobador igual al creador, resolver una no pendiente, desistir

## Reglas de negocio

- Revisión manual exige `AprobadoPor` (CHECK de la DB).

## Dependencias

- Requiere: CR-01
- Bloquea: CR-05
