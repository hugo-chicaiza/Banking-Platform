---
number: 27
title: "CR-01 | Registro de solicitud de crédito"
type: task
code: CR-01
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: L
estimate: 6
estimate_be: 3
estimate_fe: 3
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/27
---

> Como **asesor**, quiero **registrar una solicitud de crédito con monto, plazo y sistema de amortización** para **que el cliente reciba una respuesta inmediata**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Credito.CreditoSolicitud`, `Credito.SituacionFinanciera`, `Credito.TipoCredito`, `ProductosFinancieros.Producto`

## Criterios de aceptación

- [ ] La solicitud exige cliente Activo, situación financiera vigente, consentimiento de buró y declaración de licitud de fondos (CRE-06)
- [ ] Al guardarla queda evaluada: APROBADA, RECHAZADA (con motivo) o REVISION_MANUAL
- [ ] Buscar solicitudes y ver su detalle (CRE-07, CRE-08)
- [ ] Pruebas: cliente no activo, sin situación, sin consentimiento, cada resultado de la evaluación

## Reglas de negocio

- No existe estado "en evaluación": la solicitud se persiste ya evaluada.

## Dependencias

- Requiere: C-08, CR-03, CR-10, CR-11
- Bloquea: CR-02, CR-04, CR-05
