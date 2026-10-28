---
number: 66
title: "AC-02 | Fecha contable de cada operación"
type: task
code: AC-02
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: XS
estimate: 1
estimate_be: 1
estimate_fe: 
etapa: "2-3"
start_date: 2026-10-26
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/66
---

> Como **sistema**, quiero **resolver la fecha contable de cada operación (corte 19:00, fines de semana y feriados)** para **registrar todo en el día contable correcto**.

**Etapa:** 2-3 · **QA:** 0 d · **Tablas:** `Contabilidad.FechaContable`, `Contabilidad.Feriado`

## Criterios de aceptación

- [ ] Toda operación usa `Contabilidad.fn_IdFechaContable` (no se reimplementa)
- [ ] Consultar la fecha contable de una fecha y la vigente (CON-01, CON-02)
- [ ] Pruebas: antes y después del corte, viernes tarde, feriado, calendario sin la fecha (DB 51016)

## Reglas de negocio

- Antes de 19:00 de un día hábil → hoy; después, fin de semana o feriado → siguiente día contable.

## Dependencias

- Requiere: F-07 (calendario y feriados)
- Bloquea: AC-01, CJ-01
