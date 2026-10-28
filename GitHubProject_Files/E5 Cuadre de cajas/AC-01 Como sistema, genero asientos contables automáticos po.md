---
number: 65
title: "AC-01 | Asientos contables automáticos"
type: task
code: AC-01
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 4
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/65
---

> Como **sistema**, quiero **generar el asiento contable de cada operación en la misma transacción** para **que la contabilidad refleje siempre lo operado**.

**Etapa:** 4-5 · **QA:** 0 d · **Tablas:** `Contabilidad.AsientoContable`, `Contabilidad.MovimientosContables`, `Contabilidad.CuentasContables`, `Contabilidad.TiposAsiento`

## Criterios de aceptación

- [ ] Servicio interno (sin endpoint) que usan ATM, ventanilla, bóveda y crédito
- [ ] El asiento se crea en la misma transacción de DB que la operación; si falla, no queda nada
- [ ] Número con `usp_GenerarNumeroAsiento`; contabilizado con `usp_ContabilizarAsiento`
- [ ] Débitos = créditos y solo cuentas imputables
- [ ] Pruebas: un asiento por tipo de operación, asiento descuadrado, cuenta no imputable, período cerrado

## Reglas de negocio

- Triggers 56001-56012 protegen asientos contabilizados, períodos cerrados y fechas hábiles.

## Dependencias

- Requiere: AC-02, F-07 (plan de cuentas)
- Bloquea: T-03, T-05, CJ-07, CJ-08, CR-05, CR-06, CJ-05

## Pendiente

- G-06 (decidir en grupo): matriz de cuentas (debe / haber) por tipo de transacción; definir con el contador.
