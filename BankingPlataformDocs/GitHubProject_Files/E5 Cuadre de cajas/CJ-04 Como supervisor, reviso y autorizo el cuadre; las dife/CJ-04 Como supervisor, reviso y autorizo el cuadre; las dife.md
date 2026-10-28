---
number: 54
title: "CJ-04 | Autorización del cuadre"
type: task
code: CJ-04
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 2
estimate_fe: 2
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/54
---

> Como **supervisor**, quiero **autorizar el cuadre de cada cajero** para **dejar registradas y justificadas las diferencias**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Caja.CuadreCaja`

## Criterios de aceptación

- [ ] Autorizar un cuadre con conteo; el supervisor no es el cajero (CAJ-17)
- [ ] Sobrantes y faltantes exigen observación
- [ ] Pruebas: autorizar, autorizar sin conteo, misma persona, diferencia sin observación

## Reglas de negocio

- No existe estado APROBADO: la aprobación es `IdAutorizadoPor` distinto del cajero.

## Dependencias

- Requiere: CJ-03
