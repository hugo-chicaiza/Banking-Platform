---
number: 18
title: "A-02 | Consulta de saldo y cuenta"
type: task
code: A-02
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/18
---

> Como **asesor**, quiero **buscar una cuenta y ver su saldo contable, retenido y disponible** para **informar al cliente**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Cuentas.Cuenta`

## Criterios de aceptación

- [ ] Buscar cuentas por cliente, número, estado o agencia (CTA-02)
- [ ] Ver el detalle y los saldos de una cuenta (CTA-03, CTA-04)
- [ ] Disponible = saldo − retenido
- [ ] Pruebas: búsqueda por cada filtro, cuenta inexistente, cuenta cerrada

## Dependencias

- Requiere: A-01

## Pendiente

- G-16 (decidir en grupo): no hay tabla de retenciones que respalde `SaldoRetenido`; por ahora es solo lectura.
