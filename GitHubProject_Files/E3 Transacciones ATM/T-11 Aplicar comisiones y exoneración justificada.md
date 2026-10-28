---
number: 104
title: "T-11 | Comisiones y exoneración"
type: task
code: T-11
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P2
size: S
estimate: 2
estimate_be: 2
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/104
---

> Como **sistema**, quiero **cobrar la comisión de cada transacción y permitir exonerarla con motivo** para **aplicar el tarifario de la cooperativa**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Transacciones.Comisiones`, `Transacciones.ComisionTipoTransaccion`, `Transacciones.TransaccionComision`

## Criterios de aceptación

- [ ] La comisión se calcula en backend por tipo, canal y monto (`fn_CalcularComision`); nunca la envía el frontend
- [ ] Cada cobro queda en `TransaccionComision` junto a su transacción
- [ ] Una exoneración exige motivo y monto 0
- [ ] Un reintento idempotente no cobra dos veces
- [ ] Pruebas: comisión fija, porcentual con mínimo y máximo, exonerada, reintento

## Reglas de negocio

- Fijo = valor; Porcentaje = monto × valor / 100 dentro de [mínimo, máximo].

## Dependencias

- Bloquea: T-03, T-05

## Pendiente

- Quién puede exonerar y con qué flujo: nunca desde la sesión ATM.
