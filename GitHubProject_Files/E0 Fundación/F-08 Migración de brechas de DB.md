---
number: 108
title: "F-08 | Migración de brechas de DB"
type: task
code: F-08
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 3
estimate_fe: 
etapa: "1-2"
start_date: 2026-10-19
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/108
---

> Como **equipo**, quiero **aplicar las brechas de DB aprobadas** para **que las historias tengan las tablas y columnas que necesitan**.

**Etapa:** 1-2 · **QA:** 0 d · **Tablas:** ver tabla

## Criterios de aceptación

- [ ] El grupo cierra las brechas en amarillo
- [ ] Script de migración versionado con su script de reversión, solo con brechas aprobadas
- [ ] Probado en una copia antes del entorno compartido
- [ ] Diccionario de Datos actualizado
- [ ] Cada historia afectada recibe un comentario con el cambio aplicado

## Reglas de negocio

| Decisión | Brechas | Historias |
|---|---|---|
| Aplicar | G-02 hash/intentos de PIN · G-05 estado del crédito · G-08 casete de depósito ATM · G-09 flujo de cuadre · G-10 pago de cuota sin cuenta · G-13 fecha contable tras corte | A-05, T-01, T-06, CR-05, CR-07, CR-08, T-04, T-10, CJ-03, CJ-04, CJ-06, CR-06, AC-02 |
| Decidir en grupo | G-06 plantillas de asiento · G-07 conciliación persistida · G-12 claves de política · G-16 retenciones | AC-01, CJ-05, CR-02, F-07, A-02 |
| Descartar | G-01 (la autenticación vive en SeguridadDB) · G-03 · G-04 · G-11 · G-14 · G-15 · G-17 | — |

## Dependencias

- Bloquea: F-07 y las historias de la tabla

## Pendiente

- Decidir G-06, G-07, G-12 y G-16.
- G-02: `SeguridadDB` ya tiene `TarjetaPIN` con intentos y bloqueo, pero sin hash ni salt. Confirmar si la brecha se aplica ahí.
