---
number: 67
title: "AC-03 | Consulta y reverso de asientos"
type: task
code: AC-03
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P2
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/67
---

> Como **contador**, quiero **consultar asientos y reversar los incorrectos** para **corregir la contabilidad sin borrar nada**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables`, `Contabilidad.CuentasContables`

## Criterios de aceptación

- [ ] Ver el plan de cuentas (CON-03) y buscar asientos (CON-04, CON-05)
- [ ] Reversar un asiento contabilizado con un asiento inverso enlazado (CON-06)
- [ ] Pruebas: reverso, doble reverso, asiento no contabilizado, período cerrado

## Dependencias

- Requiere: AC-01
