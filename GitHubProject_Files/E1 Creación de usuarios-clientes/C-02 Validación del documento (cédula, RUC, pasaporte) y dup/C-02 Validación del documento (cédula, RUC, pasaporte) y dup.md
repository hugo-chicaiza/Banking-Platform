---
number: 42
title: "C-02 | Validación de documento y duplicados"
type: task
code: C-02
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P1
size: S
estimate: 2
estimate_be: 1
estimate_fe: 1
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/42
---

> Como **asesor**, quiero **validar la cédula, RUC o pasaporte y saber si el cliente ya existe** para **no registrar documentos inválidos ni duplicados**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Clientes.Cliente`

## Criterios de aceptación

- [ ] El formulario de C-01 valida el documento al salir del campo (CLI-01)
- [ ] Se informa si el documento es inválido o ya está registrado (con enlace al cliente)
- [ ] El backend repite la validación al crear (CLI-02)
- [ ] Pruebas: cédula, RUC y pasaporte válidos e inválidos, duplicado, alta concurrente del mismo documento

## Reglas de negocio

- Cédula: 10 dígitos, módulo 10. RUC: 13 dígitos terminados en `001`. Pasaporte: 5 a 13 alfanuméricos (`CK_Cliente_Identificacion`).
- `Identificacion` es única en `Clientes.Cliente`.

## Dependencias

- Requiere: F-04
- Bloquea: C-01
