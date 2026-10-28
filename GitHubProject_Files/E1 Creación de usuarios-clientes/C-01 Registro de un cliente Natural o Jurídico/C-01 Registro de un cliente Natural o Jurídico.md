---
number: 39
title: "C-01 | Registro de cliente Natural o Jurídico"
type: task
code: C-01
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P1
size: L
estimate: 6
estimate_be: 3
estimate_fe: 3
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/39
---

> Como **asesor**, quiero **registrar un cliente Natural o Jurídico con su dirección principal y consentimiento de datos** para **incorporarlo a la cooperativa**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Clientes.Cliente`, `Clientes.Direcciones`, `Clientes.ClientesHis`, `Catalogo.ActividadEconomica`, `Catalogo.Paises`, `Catalogo.Ciudad`

## Criterios de aceptación

- [ ] El formulario cambia según el tipo: Natural (nombres, apellidos, género, estado civil, nacimiento) o Jurídico (razón social, constitución)
- [ ] El consentimiento de datos es obligatorio
- [ ] Se registra la dirección principal con ciudad, calle y referencia
- [ ] Actividad, país y ciudad salen de los catálogos (F-09)
- [ ] El cliente queda en `Pendiente` hasta su evaluación de riesgo (C-08)
- [ ] Cliente, dirección e historial se guardan en una sola transacción: si algo falla, no queda nada
- [ ] Pruebas: natural, jurídico, campos faltantes, sin consentimiento, catálogo inexistente, rollback

## Reglas de negocio

- `CK_Cliente_TipoPersona`: Natural exige apellidos, género y estado civil; Jurídico exige razón social y no admite esos campos.
- Fecha de nacimiento o constitución anterior a hoy.

## Dependencias

- Requiere: F-03, F-04, F-09, C-02
- Bloquea: C-08, A-01
