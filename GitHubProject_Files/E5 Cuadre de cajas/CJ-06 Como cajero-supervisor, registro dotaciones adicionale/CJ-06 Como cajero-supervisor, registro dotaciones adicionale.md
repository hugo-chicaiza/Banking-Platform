---
number: 56
title: "CJ-06 | Dotaciones adicionales y devoluciones a bóveda"
type: task
code: CJ-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/56
---

> Como **cajero o supervisor**, quiero **pedir más efectivo a bóveda y devolver el excedente** para **operar sin quedarme sin efectivo y cerrar la caja**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Caja.DotacionesCaja`, `Caja.DevolucionesCaja`, `Boveda.MovimientoBoveda`

## Criterios de aceptación

- [ ] Registrar dotación ADICIONAL después de la INICIAL (CAJ-07) y ver las dotaciones (CAJ-08)
- [ ] Devolver a bóveda lo contado en el cuadre (CAJ-15)
- [ ] Ambas operaciones con doble custodia
- [ ] Pruebas: adicional sin inicial, devolución distinta al conteo, doble devolución, misma persona

## Reglas de negocio

- `usp_RegistrarDotacionCaja` y `usp_RegistrarDevolucionCaja`; las alertas de bóveda no bloquean.

## Dependencias

- Requiere: CJ-01
- Bloquea: CJ-03
