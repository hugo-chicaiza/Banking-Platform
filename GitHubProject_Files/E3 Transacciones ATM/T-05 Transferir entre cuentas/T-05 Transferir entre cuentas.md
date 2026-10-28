---
number: 10
title: "T-05 | Transferencia entre cuentas en ATM"
type: task
code: T-05
parent: "[[E3 Transacciones ATM]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/10
---

> Como **cliente**, quiero **transferir desde mi cuenta a otra cuenta de la cooperativa** para **mover dinero sin ir a ventanilla**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`

## Criterios de aceptación

- [ ] Se valida cuenta destino, que sea distinta del origen, fondos y cupos (ATM-05)
- [ ] Quedan dos transacciones relacionadas (enviada y recibida) y dos movimientos, juntos o ninguno
- [ ] Reintento idempotente por `registroUnico`
- [ ] Pruebas: transferencia correcta, destino inexistente, misma cuenta, fondos insuficientes, cupo excedido

## Dependencias

- Requiere: T-01, AC-01
