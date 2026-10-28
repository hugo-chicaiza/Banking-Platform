---
number: 1
title: "Épica 2: Cuentas"
type: epic
code: E2
parent: 
status: Épicas
priority: P1
size: 
estimate: 23
estimate_be: 
estimate_fe: 
etapa: "2-3"
start_date: 2026-10-26
target_date: 2026-11-09
state: open
labels: []
assignees: [Keldorein]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/1
---

## Objetivo

Abrir y administrar las cuentas de los clientes y emitir sus tarjetas de débito con PIN, estados y cupos por canal.

## Alcance

- Incluye: apertura (A-01), saldos (A-02), estados de cuenta (A-03), emisión de tarjeta (A-04), PIN y estados de tarjeta (A-05), cupos por canal (A-06), movimientos (A-07).
- No incluye: depósito de apertura (lo registra caja, CJ-07) ni operaciones en ATM (Épica 3).

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Avance 25 % | 2026-11-04 | A-01 a A-03 |
| Avance 50 % | 2026-11-09 | A-04 a A-07 |

## Decisiones pendientes

- Dónde se guarda el hash del PIN (G-02, `SeguridadDB.TarjetaPIN`).
- Formato de `NumeroCuenta`.

## Criterios de finalización

- [ ] A-01 a A-07 cerradas y aprobadas por QA
- [ ] Flujo probado: cliente Activo → cuenta → depósito de apertura en caja → tarjeta con PIN activa
