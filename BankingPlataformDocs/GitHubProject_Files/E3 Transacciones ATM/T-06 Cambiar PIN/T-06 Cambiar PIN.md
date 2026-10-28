---
number: 11
title: "T-06 | Cambio de PIN en ATM"
type: task
code: T-06
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P2
size: S
estimate: 2
estimate_be: 1
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/11
---

> Como **cliente**, quiero **cambiar mi PIN en el ATM** para **mantener segura mi tarjeta**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Tarjeta.TarjetaHis` · `TarjetaPIN` (SeguridadDB)

## Criterios de aceptación

- [ ] Se exige el PIN actual y un PIN nuevo no trivial (ATM-06)
- [ ] Solo se guarda hash + salt; el historial no contiene el PIN
- [ ] Pruebas: cambio correcto, PIN actual incorrecto, PIN débil, PIN igual al anterior

## Dependencias

- Requiere: T-01, F-08 (G-02)
