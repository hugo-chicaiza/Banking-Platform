---
number: 57
title: "C-07 | Direcciones del cliente"
type: task
code: C-07
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/57
---

> Como **asesor**, quiero **agregar, editar, dar de baja y elegir la dirección principal del cliente** para **tener sus datos de contacto correctos**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Clientes.Direcciones`, `Clientes.ClientesHis`

## Criterios de aceptación

- [ ] Listar, agregar y editar direcciones (CLI-09 a CLI-11)
- [ ] Marcar otra dirección como principal desmarca la anterior en la misma operación
- [ ] Dar de baja es lógica; la principal no se elimina sin elegir otra antes (CLI-12)
- [ ] Altas y cambios quedan en `ClientesHis`
- [ ] Pruebas: alta, edición, cambio de principal, baja, baja de la principal

## Reglas de negocio

- Una sola dirección principal activa por cliente (`UX_Direcciones_Principal`).

## Dependencias

- Requiere: C-01, F-09
