---
number: 31
title: "CR-05 | Desembolso y generación de cuotas"
type: task
code: CR-05
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 4
estimate_fe: 1
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/31
---

> Como **sistema**, quiero **desembolsar el crédito aprobado a la cuenta del cliente y generar su plan y cuotas** para **que el cliente reciba el dinero y empiece a pagar**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Credito.CreditoDesembolso`, `Credito.CreditoPlanAmortizacion`, `Credito.CreditoCuota`, `Credito.CreditoResumen`, `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`

## Criterios de aceptación

- [ ] Solo solicitudes APROBADAS y dentro de `VIGENCIA_APROBACION` (CRE-12)
- [ ] La cuenta destino es del cliente y está Activa
- [ ] Desembolso, transacción, crédito a la cuenta, plan v1, cuotas, resumen y asiento quedan juntos o nada
- [ ] Pruebas: desembolso correcto, solicitud no aprobada, aprobación vencida, cuenta ajena, monto excedido

## Reglas de negocio

- Triggers: 55005 (no aprobada), 55006 (vencida), 55007 (supera monto), 55008 (transacción no coincide).

## Dependencias

- Requiere: CR-01, CR-04, A-01, AC-01
- Bloquea: CR-06, CR-07, CR-08
