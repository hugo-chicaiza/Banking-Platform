---
number: 105
title: "T-12 | Administración de terminales ATM"
type: task
code: T-12
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P3
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/105
---

> Como **administrador**, quiero **dar de alta terminales y cambiar su estado** para **controlar qué ATM están en servicio**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `ATM.ATM`

## Criterios de aceptación

- [ ] Listar terminales por agencia y estado (ATM-10)
- [ ] Alta con código único y canal que exige terminal (ATM-11)
- [ ] Cambio de estado activo / inactivo / mantenimiento con motivo (ATM-12)
- [ ] Un terminal no activo rechaza sesiones
- [ ] Pruebas: alta, código duplicado, cada cambio de estado, sesión en terminal inactivo

## Dependencias

- Bloquea: T-01, T-09

## Pendiente

- Confirmar con el DBA los valores de `ATM.Estado` (el export no trae el CHECK).
