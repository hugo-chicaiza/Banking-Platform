---
number: 103
title: "T-10 | Cuadre diario del ATM"
type: task
code: T-10
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P2
size: M
estimate: 4
estimate_be: 2
estimate_fe: 2
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/103
---

> Como **supervisor**, quiero **cuadrar cada ATM al final del día (teórico vs físico)** para **detectar diferencias de efectivo**.

**Etapa:** 4-5 · **QA:** 0 d · **Tablas:** `ATM.CuadreATM`, `ATM.GavetaMovimiento`, `Transacciones.Transaccion`

## Criterios de aceptación

- [ ] Generar el cuadre del día con el saldo teórico (ATM-15); uno por ATM y fecha contable
- [ ] Registrar el conteo físico y calcular la diferencia (ATM-16)
- [ ] Con diferencia se exige observación y autorización de otra persona
- [ ] Consultar cuadres para la conciliación (ATM-17)
- [ ] Pruebas: cuadrado, sobrante, faltante, cuadre duplicado

## Reglas de negocio

- Estados: PENDIENTE_ARQUEO → EN_REVISION → CUADRADO | CON_DIFERENCIA → CERRADO · ANULADO.

## Dependencias

- Requiere: T-03, T-09
- Bloquea: CJ-05
