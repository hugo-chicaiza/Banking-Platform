---
number: 49
title: "C-06 | Perfil del cliente"
type: task
code: C-06
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P2
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/49
---

> Como **asesor**, quiero **ver el perfil del cliente con su riesgo, cuentas, tarjetas y créditos** para **atenderlo con toda su información en una pantalla**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Clientes.*`, `Cuentas.Cuenta`, `Tarjeta.Tarjeta`, `Credito.CreditoSolicitud`, `Credito.CreditoResumen`

## Criterios de aceptación

- [ ] Muestra datos generales, estado y evaluación de riesgo vigente
- [ ] Lista cuentas, tarjetas (solo máscara) y créditos con su estado
- [ ] Un cliente sin productos muestra secciones vacías, no errores
- [ ] Desde el perfil se navega a movimientos de cuenta (A-07) y detalle de crédito (CR-07)
- [ ] Pruebas: con productos, sin productos, cliente inexistente, permisos por rol

## Dependencias

- Requiere: C-03, C-08, A-02, A-04, CR-07
