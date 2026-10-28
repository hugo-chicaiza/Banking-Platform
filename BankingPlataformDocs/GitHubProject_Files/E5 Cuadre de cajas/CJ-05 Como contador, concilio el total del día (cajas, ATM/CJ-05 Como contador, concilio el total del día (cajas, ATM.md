---
number: 55
title: "CJ-05 | Conciliación diaria"
type: task
code: CJ-05
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/55
---

> Como **contador**, quiero **conciliar el día (cajas, ATM, créditos, bóveda) contra contabilidad** para **cerrar el día sin diferencias**.

**Etapa:** 4-5 · **QA:** 0 d · **Tablas:** `Caja.CuadreCaja`, `ATM.CuadreATM`, `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables`

## Criterios de aceptación

- [ ] Ver la conciliación por fecha contable y agencia (CON-07), con cuadres de ATM (ATM-17)
- [ ] Cada diferencia muestra su origen (caja, ATM, crédito, bóveda)
- [ ] Se listan transacciones sin asiento
- [ ] Pruebas: día cuadrado, diferencia en caja, transacción sin asiento

## Reglas de negocio

- Se apoya en `vw_ConciliacionEfectivo`, `vw_TransaccionesSinAsiento` y `usp_ValidarCierreDiario` (DB 51601 bloquea el cierre).

## Dependencias

- Requiere: CJ-03, T-10, AC-01

## Pendiente

- G-07: decidir si se guarda el resultado de la conciliación.
