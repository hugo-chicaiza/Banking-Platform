---
number: 63
title: "CJ-09 | Gestión de bóvedas"
type: task
code: CJ-09
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/63
---

> Como **supervisor**, quiero **ver las bóvedas con su saldo por denominación y registrar traslados, ajustes y provisiones** para **controlar el efectivo de la agencia**.

**Etapa:** 4-5 · **QA:** 0 d · **Tablas:** `Boveda.Boveda`, `Boveda.BovedaDenominacion`, `Boveda.MovimientoBoveda`, `Boveda.MovimientoBovedaDenominacion`

## Criterios de aceptación

- [ ] Listar bóvedas y ver su saldo por denominación (BOV-01, BOV-02)
- [ ] Ver movimientos por tipo y fecha (BOV-03)
- [ ] Registrar traslado (dos movimientos ligados), ajuste o provisión con doble custodia (BOV-04)
- [ ] Pruebas: traslado, traslado sin destino, egreso sin piezas, misma persona autoriza

## Dependencias

- Bloquea: CJ-01, T-09
