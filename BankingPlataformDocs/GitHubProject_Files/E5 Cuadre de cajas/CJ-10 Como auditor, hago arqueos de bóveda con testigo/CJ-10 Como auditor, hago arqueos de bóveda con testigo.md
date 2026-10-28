---
number: 64
title: "CJ-10 | Arqueo de bóveda con testigo"
type: task
code: CJ-10
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P3
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/64
---

> Como **auditor**, quiero **arquear una bóveda con un testigo** para **verificar que el efectivo coincide con lo registrado**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Boveda.ArqueoBoveda`, `Boveda.ArqueoBovedaDenominacion`

## Criterios de aceptación

- [ ] Registrar el conteo por denominación con un testigo distinto (BOV-05)
- [ ] Aprobar el arqueo; si hay diferencia se genera el ajuste (BOV-06)
- [ ] Pruebas: arqueo sin diferencia, faltante, sobrante, testigo igual al arqueador

## Dependencias

- Requiere: CJ-09
