---
number: 53
title: "CJ-03 | Cuadre y cierre de caja"
type: task
code: CJ-03
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/53
---

> Como **cajero**, quiero **cuadrar mi caja (conteo físico vs esperado) y cerrar la jornada** para **entregar el efectivo y justificar diferencias**.

**Etapa:** 4 · **QA:** 0 d · **Tablas:** `Caja.CuadreCaja`, `Caja.JornadasCaja`

## Criterios de aceptación

- [ ] Generar el cuadre con los totales del día (CAJ-13) y consultarlo (CAJ-14)
- [ ] Registrar el conteo físico; el sistema calcula diferencia y estado (CAJ-16)
- [ ] Cerrar la jornada con cuadre contado y, si hay diferencia, autorizado (CAJ-18)
- [ ] Supervisor y contador consultan jornadas (CAJ-02)
- [ ] Pruebas: cuadrado, sobrante, faltante, cierre sin conteo, cierre sin autorización

## Reglas de negocio

- Diferencia = físico − (inicial + dotaciones + depósitos + pagos − retiros − devoluciones).
- Estados: PENDIENTE → CUADRADO | SOBRANTE | FALTANTE.

## Dependencias

- Requiere: CJ-02, CJ-06
- Bloquea: CJ-04, CJ-05

## Pendiente

- G-09: el procedimiento de devolución exige el conteo antes; alinear el orden devolución / conteo.
