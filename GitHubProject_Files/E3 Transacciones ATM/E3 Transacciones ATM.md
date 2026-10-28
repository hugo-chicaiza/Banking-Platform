---
number: 3
title: "Épica 3: Transacciones ATM"
type: epic
code: E3
parent: 
status: Épicas
priority: P1
size: 
estimate: 39
estimate_be: 
estimate_fe: 
etapa: "3-5"
start_date: 2026-11-04
target_date: 2026-11-23
state: open
labels: []
assignees: [Squierdan]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/3
---

## Objetivo

Que el cliente opere en el cajero automático con su tarjeta y PIN, y que cada operación quede trazada, cobrada y contabilizada; incluye abastecer y cuadrar los ATM.

## Alcance

- Incluye: tarjeta y PIN (T-01), saldo (T-02), retiro (T-03), transferencia (T-05), cambio de PIN (T-06), movimientos (T-07), trazabilidad y reversos (T-08), abastecimiento (T-09), cuadre (T-10), comisiones (T-11), terminales (T-12).
- No incluye: depósito en ATM (T-04) hasta decidir la brecha G-08.

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Avance 50 % | 2026-11-09 | T-01, T-02, T-03, T-05, T-06, T-08 |
| Avance 75 % | 2026-11-16 | T-07, T-09, T-11 |
| Avance 100 % | 2026-11-23 | T-10, T-12; T-04 solo si se aprueba |

## Decisiones pendientes

- G-02: hash e intentos del PIN (`SeguridadDB.TarjetaPIN`).
- G-08: ¿el ATM acepta depósitos? Si no, cerrar T-04.
- Valor de N para bloquear la tarjeta y cómo se autentica el terminal.

## Criterios de finalización

- [ ] Historias P1 cerradas y probadas con datos ficticios
- [ ] Retiro, reverso y cuadre del ATM conciliados con contabilidad (CJ-05)
