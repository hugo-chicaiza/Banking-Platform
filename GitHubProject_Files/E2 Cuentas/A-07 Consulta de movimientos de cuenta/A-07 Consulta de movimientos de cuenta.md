---
number: 123
title: "A-07 | Movimientos de cuenta"
type: task
code: A-07
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/123
---

> Como **asesor**, quiero **consultar los movimientos de una cuenta por fechas y tipo** para **entregar el estado de cuenta al cliente**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Cuentas.MovimientoTransaccion`, `Transacciones.Transaccion`

## Criterios de aceptación

- [ ] Filtrar por rango de fechas y tipo de transacción, con paginación (CTA-06)
- [ ] Cada movimiento muestra fecha, tipo (débito/crédito), monto, saldo posterior y comprobante
- [ ] Los reversos se ven como movimientos propios, sin borrar el original
- [ ] Pruebas: rango inválido, sin movimientos, filtros combinados, cuenta con reversos

## Dependencias

- Requiere: A-01
