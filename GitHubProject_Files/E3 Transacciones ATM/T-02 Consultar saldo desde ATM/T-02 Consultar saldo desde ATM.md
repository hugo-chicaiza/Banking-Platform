---
number: 7
title: "T-02 | Consulta de saldo en ATM"
type: task
code: T-02
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/7
---

> Como **cliente**, quiero **consultar mi saldo en el ATM** para **saber cuánto puedo retirar**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Cuentas.Cuenta`, `Transacciones.Transaccion`

## Criterios de aceptación

- [ ] Muestra saldo disponible y contable de una cuenta de la sesión (ATM-02)
- [ ] Queda una transacción `Consulta` con su código de respuesta
- [ ] Si la consulta tiene costo, se cobra con una transacción `Cobro_Comision` aparte
- [ ] Pruebas: consulta correcta, cuenta ajena, cuenta no activa, consulta con comisión

## Reglas de negocio

- Una consulta no mueve saldo ni genera asiento (DB 53003, 56012).

## Dependencias

- Requiere: T-01
