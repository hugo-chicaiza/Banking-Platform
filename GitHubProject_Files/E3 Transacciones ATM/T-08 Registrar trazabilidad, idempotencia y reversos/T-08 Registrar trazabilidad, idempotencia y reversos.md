---
number: 19
title: "T-08 | Trazabilidad, idempotencia y reversos"
type: task
code: T-08
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 3
estimate_fe: 0
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/19
---

> Como **auditor**, quiero **que cada transacción quede trazada y pueda reversarse de forma controlada** para **reconstruir cualquier operación**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Transacciones.Transaccion`, `Catalogo.CodigosRespuesta`, `Cuentas.MovimientoTransaccion`

## Criterios de aceptación

- [ ] Toda transacción guarda `RegistroUnico`, STAN, RRN, MTI y código de respuesta ISO
- [ ] Las rechazadas guardan un código distinto de `00`
- [ ] Reverso del terminal (ATM-08) y reverso supervisado (TRX-03) con MTI 0400, ligados a la original
- [ ] Consulta de transacciones y su detalle (TRX-01, TRX-02)
- [ ] Pruebas: reintento idempotente, rechazo, reverso, doble reverso, reverso con jornada cerrada

## Reglas de negocio

- `RegistroUnico` (char 12, único) es la clave de idempotencia; lo envía el cliente.
- Solo se reversa una transacción Normal, Completada y de la misma cuenta (DB 53002).

## Dependencias

- Bloquea: T-03, T-05, CJ-07, CJ-08
