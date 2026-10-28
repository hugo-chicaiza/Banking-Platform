---
number: 21
title: "F-05 | Layout base y ruteo protegido por rol"
type: task
code: F-05
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 
estimate_fe: 5
etapa: "1"
start_date: 2026-10-19
target_date: 2026-10-26
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/21
---

> Como **usuario del sistema**, quiero **un layout base con menú y rutas según mi rol** para **ver solo los módulos que me corresponden**.

**Etapa:** 1 · **QA:** 0 d · **Tablas:** —

## Criterios de aceptación

- [ ] Layout Angular con encabezado, menú lateral y contenido, adaptable a pantalla
- [ ] Rutas para clientes, cuentas, ATM, créditos, caja y contabilidad
- [ ] Guard: sin sesión → login; rol sin permiso → "acceso denegado"
- [ ] El menú se arma con los `roles` de AUT-04
- [ ] Páginas 404 y acceso denegado
- [ ] Funciona contra el mock de F-01 mientras F-03 no esté listo

## Dependencias

- Requiere: F-01 (mock), F-03 (AUT-04)
