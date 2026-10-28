---
number: 43
title: "Épica 5: Cuadre de cajas"
type: epic
code: E5
parent: 
status: Épicas
priority: P1
size: 
estimate: 54
estimate_be: 
estimate_fe: 
etapa: "2-5"
start_date: 2026-10-26
target_date: 2026-11-23
state: open
labels: []
assignees: [Zark35]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/43
---

## Objetivo

Operar la ventanilla con control del efectivo: jornada de caja con dotación desde bóveda, depósitos y retiros, cuadre y cierre con doble custodia, gestión de bóvedas, contabilidad automática y conciliación diaria.

## Alcance

- Incluye: jornada y dotación (CJ-01), operaciones en jornada (CJ-02), cuadre (CJ-03), autorización (CJ-04), conciliación (CJ-05), dotaciones adicionales y devoluciones (CJ-06), depósito con series (CJ-07), retiro (CJ-08), bóvedas (CJ-09), arqueos (CJ-10), asientos automáticos (AC-01), fecha contable (AC-02), consulta y reverso de asientos (AC-03).

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Avance 25 % | 2026-11-04 | AC-02 (parcial) |
| Avance 75 % | 2026-11-16 | CJ-01 a CJ-08, AC-01 (primera versión) |
| Avance 100 % | 2026-11-23 | CJ-05, CJ-09, AC-01 completo; CJ-10 y AC-03 si hay holgura |

## Flujo de la jornada

Abrir jornada → dotación INICIAL (doble custodia) → depósitos, retiros y pagos → cuadre → devolución a bóveda → conteo → autorización → cierre.

## Decisiones pendientes

- G-09: orden devolución / conteo (el procedimiento exige conteo antes de devolver).
- G-06: plantillas de asiento por tipo de transacción (AC-01).
- G-07: guardar o no el resultado de la conciliación.
- Issues marcados **[OBSOLETO]**: cerrarlos como *not planned*.

## Criterios de finalización

- [ ] Historias P1 cerradas y probadas
- [ ] Un día completo de una agencia cuadra en caja, bóveda, ATM y contabilidad
