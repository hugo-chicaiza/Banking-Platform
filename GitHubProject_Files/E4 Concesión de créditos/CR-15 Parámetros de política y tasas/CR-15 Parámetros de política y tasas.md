---
number: 73
title: "CR-15 | Parámetros de política y tasas"
type: task
code: CR-15
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/73
---

> Como **administrador**, quiero **mantener los parámetros de política** para **ajustar la evaluación sin tocar código**.

**Etapa:** 5 · **QA:** 0 d · **Tablas:** `Credito.ParametroPolitica`, `Credito.TasaInteres`

## Criterios de aceptación

- [ ] Ver los parámetros vigentes (CRE-26)
- [ ] Cambiar un parámetro crea una versión nueva y cierra la anterior (CRE-27)
- [ ] Pruebas: cambio de valor, clave inexistente, valor fuera de rango

## Reglas de negocio

- Mientras no exista, los parámetros y tasas se cargan por semilla (F-07).

## Dependencias

- Requiere: F-07
