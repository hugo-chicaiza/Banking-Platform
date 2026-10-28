---
number: 102
title: "T-09 | Abastecimiento de ATM desde bóveda"
type: task
code: T-09
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/102
---

> Como **operador**, quiero **abastecer las gavetas del ATM desde la bóveda con doble custodia** para **que el ATM tenga efectivo**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `ATM.Gaveta`, `ATM.GavetaMovimiento`, `Boveda.MovimientoBoveda`, `Boveda.BovedaDenominacion`

## Criterios de aceptación

- [ ] Ver gavetas con denominación, capacidad y cantidad actual (ATM-13)
- [ ] Abastecer por gaveta sin superar su capacidad, con bóveda de la misma agencia (ATM-14)
- [ ] Quien autoriza es distinto de quien registra
- [ ] Egreso de bóveda, ingreso a gavetas y asiento quedan juntos
- [ ] Pruebas: abastecimiento correcto, capacidad excedida, bóveda sin piezas, misma persona autoriza

## Reglas de negocio

- Movimiento de bóveda tipo `AbastecimientoATM`.

## Dependencias

- Requiere: T-12, CJ-09, AC-01
