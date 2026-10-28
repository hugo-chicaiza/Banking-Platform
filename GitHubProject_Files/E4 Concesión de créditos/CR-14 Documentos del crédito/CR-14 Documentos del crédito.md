---
number: 72
title: "CR-14 | Documentos del crédito"
type: task
code: CR-14
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P3
size: S
estimate: 2
estimate_be: 1
estimate_fe: 1
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/72
---

> Como **asesor**, quiero **adjuntar los documentos del crédito** para **tener el expediente completo**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Credito.CreditoDocumento`

## Criterios de aceptación

- [ ] Registrar metadatos y hash del documento (CRE-25)
- [ ] Un documento nuevo del mismo tipo reemplaza al anterior
- [ ] Pruebas: alta, reemplazo, anulación

## Dependencias

- Requiere: CR-01

## Pendiente

- Dónde se almacena el archivo: la DB solo guarda metadatos.
