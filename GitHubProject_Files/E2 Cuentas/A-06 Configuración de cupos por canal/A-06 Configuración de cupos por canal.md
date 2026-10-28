---
number: 62
title: "A-06 | Cupos por canal"
type: task
code: A-06
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P2
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/62
---

> Como **supervisor**, quiero **ver y ajustar los cupos de una cuenta por canal** para **limitar lo que el cliente puede mover en cada canal**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Canal.CanalCupoClienteCustom`, `Canal.CuposModHis`, `Canal.ProductoCanalCupo`

## Criterios de aceptación

- [ ] Ver el cupo que rige por canal, lo consumido y lo disponible (CTA-07)
- [ ] Definir un cupo personalizado sin superar el del producto (CTA-08)
- [ ] Ver el historial de cambios de cupo (CTA-09)
- [ ] Pruebas: cupo del producto, cupo personalizado, tope excedido, valores incoherentes, historial

## Reglas de negocio

- Cupo vigente = personalizado vigente o, si no hay, el del subproducto (`Canal.fn_CupoVigente`).
- Los cupos los aplica `Transacciones.usp_AutorizarOperacion` en cada operación (códigos 61 y 65).

## Dependencias

- Requiere: A-01
