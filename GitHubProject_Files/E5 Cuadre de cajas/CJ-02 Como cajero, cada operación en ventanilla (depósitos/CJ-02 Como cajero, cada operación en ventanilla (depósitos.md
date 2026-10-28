---
number: 52
title: "CJ-02 | Operaciones de ventanilla asociadas a la jornada"
type: task
code: CJ-02
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/52
---

> Como **cajero**, quiero **que cada operación de ventanilla quede asociada a mi jornada** para **cuadrar el efectivo al final del día**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Caja.MovimientosCaja`, `Caja.TipoMovimientoCaja`, `Transacciones.Transaccion`

## Criterios de aceptación

- [ ] Depósitos, retiros y pagos de cuota exigen jornada ABIERTA del cajero
- [ ] Cada operación crea un movimiento de caja con su tipo y naturaleza (ingreso / egreso)
- [ ] Ver los movimientos de la jornada (CAJ-12)
- [ ] Pruebas: operación sin jornada, con jornada cerrada, movimientos de cada tipo

## Reglas de negocio

- Un movimiento de caja por transacción; el canal Ventanilla exige jornada (DB 53001).

## Dependencias

- Requiere: CJ-01, F-09 (CAT-10)
- Relacionadas: CJ-07, CJ-08, CR-06
