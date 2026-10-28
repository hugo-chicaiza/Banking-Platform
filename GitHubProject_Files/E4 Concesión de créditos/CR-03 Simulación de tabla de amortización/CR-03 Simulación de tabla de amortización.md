---
number: 29
title: "CR-03 | Simulación de tabla de amortización"
type: task
code: CR-03
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/29
---

> Como **asesor**, quiero **simular la tabla de amortización con seguros e impuestos** para **mostrar al cliente la cuota y el costo total antes de solicitar**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Credito.TasaInteres`, `Credito.Seguro`, `Credito.Impuesto`, `Credito.TipoCreditoSeguro`, `Credito.TipoCreditoImpuesto`

## Criterios de aceptación

- [ ] Consultar condiciones vigentes del tipo de crédito para un monto y plazo (CRE-01)
- [ ] Simular con sistema FRANCES o ALEMAN sin guardar nada (CRE-02)
- [ ] El plan muestra capital, interés, seguros, impuestos y saldo por cuota, más los totales
- [ ] Pruebas: francés, alemán, monto fuera de rango, plazo excedido, redondeo de la última cuota

## Dependencias

- Requiere: F-09 (CAT-09)
- Bloquea: CR-01, CR-05
