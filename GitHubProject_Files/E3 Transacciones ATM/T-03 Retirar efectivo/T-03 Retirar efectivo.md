---
number: 8
title: "T-03 | Retiro de efectivo en ATM"
type: task
code: T-03
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P1
size: L
estimate: 7
estimate_be: 5
estimate_fe: 2
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/8
---

> Como **cliente**, quiero **retirar efectivo en el ATM** para **disponer de mi dinero**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Cuentas.Cuenta`, `Cuentas.MovimientoTransaccion`, `ATM.Gaveta`, `ATM.GavetaMovimiento`, `Canal.*`, `Transacciones.Comisiones`

## Criterios de aceptación

- [ ] Se valida disponible, cupos del canal y efectivo por denominación antes de dispensar (ATM-03)
- [ ] Débito, comisión, descuento de gavetas y asiento ocurren juntos o no ocurren
- [ ] Reintentar con el mismo `registroUnico` devuelve el comprobante original
- [ ] Si la dispensa falla, el terminal reversa (ATM-08) y el saldo vuelve
- [ ] Pruebas: retiro correcto, fondos insuficientes, cupo excedido, ATM sin billetes, reintento, reverso

## Reglas de negocio

- La autorización la decide `Transacciones.usp_AutorizarOperacion` (00, 05, 51, 61, 65).

## Dependencias

- Requiere: T-01, T-09, T-11, AC-01
