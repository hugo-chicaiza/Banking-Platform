---
number: 45
title: "C-03 | Búsqueda y listado de clientes"
type: task
code: C-03
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 1
estimate_fe: 2
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/45
---

> Como **asesor**, quiero **buscar y listar clientes con filtros y paginación** para **encontrar rápido al cliente que atiendo**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Clientes.Cliente`, `Clientes.Direcciones`

## Criterios de aceptación

- [ ] Búsqueda parcial por nombre, razón social o identificación; filtro exacto por identificación, tipo y estado
- [ ] Listado paginado y ordenable, con total de resultados
- [ ] Mensaje claro cuando no hay resultados
- [ ] Desde el listado se abre el detalle del cliente (CLI-04)
- [ ] Pruebas: búsqueda exacta y parcial, filtros combinados, paginación, sin resultados, cliente inexistente

## Dependencias

- Requiere: F-03, F-05
