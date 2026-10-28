---
number: 15
title: "F-01 | Validación del contrato OpenAPI y mock server"
type: task
code: F-01
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 3
estimate_fe: 1
etapa: "1"
start_date: 2026-10-19
target_date: 2026-10-26
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/15
---

> Como **equipo**, quiero **validar el contrato OpenAPI con FE y QA y publicar un mock server** para **que frontend y QA avancen sin esperar al backend**.

**Etapa:** 1 · **QA:** 0 d · **Tablas:** —

## Criterios de aceptación

- [ ] `openapi.yaml` (128 endpoints) revisado y aprobado por BE, FE y QA
- [ ] Mock server (p. ej. Prism) levantado desde el YAML responde los ejemplos de cada endpoint
- [ ] Contrato visible en Swagger UI
- [ ] Todo cambio de contrato entra por pull request sobre el YAML

## Reglas de negocio

- El contrato base ya existe; el esfuerzo es revisión y mock, no redacción.
- Usar la estructura del piloto del PR #106 (ATM-13 con Swagger UI).

## Dependencias

- Bloquea: F-05 (mock de AUT-04), F-06
