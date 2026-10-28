---
number: 51
title: "CJ-01 | Apertura de jornada con dotación inicial"
type: task
code: CJ-01
parent: "[[E5 Cuadre de cajas]]"
status: Backlog
priority: P1
size: L
estimate: 6
estimate_be: 3
estimate_fe: 3
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/51
---

> Como **cajero**, quiero **abrir mi jornada de caja con la dotación inicial desde bóveda** para **empezar a atender en ventanilla**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Caja.CajaFisica`, `Caja.JornadasCaja`, `Caja.DotacionesCaja`, `Caja.CajerosAsignadosAgencia`, `Boveda.*`

## Criterios de aceptación

- [ ] Elegir una caja física libre de mi agencia y abrir la jornada (CAJ-01, CAJ-03)
- [ ] Registrar la dotación INICIAL con desglose y autorización de otra persona (CAJ-07)
- [ ] Ver mi jornada actual y su detalle (CAJ-04, CAJ-05)
- [ ] Un supervisor cancela una jornada sin movimientos (CAJ-06)
- [ ] Pruebas: sin asignación, caja en uso, segunda jornada, dotación distinta al inicial, misma persona autoriza, bóveda sin piezas

## Reglas de negocio

- Una jornada abierta por cajero y por caja; sin dotación INICIAL no se opera.
- La dotación usa `Caja.usp_RegistrarDotacionCaja` (errores 51001-51016).

## Dependencias

- Requiere: C-05, CJ-09, AC-02
- Bloquea: CJ-02 a CJ-08
