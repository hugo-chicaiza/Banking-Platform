---
number: 13
title: "Épica 0: Fundación"
type: epic
code: E0
parent: 
status: Épicas
priority: P1
size: 
estimate: 38
estimate_be: 
estimate_fe: 
etapa: "1-2"
start_date: 2026-10-19
target_date: 2026-11-04
state: open
labels: []
assignees: [ismapinto2007-sys]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/13
---

## Objetivo

Dejar lista la base técnica que usan todas las épicas: contrato OpenAPI con mock, entornos y CI, autenticación por roles, formato de errores y auditoría, layout del frontend, estrategia de pruebas, datos semilla, brechas de DB y catálogos.

## Alcance

- Incluye: OpenAPI + mock (F-01), proyecto y CI (F-02), login JWT y roles (F-03), errores ProblemDetails y auditoría (F-04), layout y ruteo por rol (F-05), estrategia de pruebas (F-06), semilla (F-07), migración de brechas (F-08), API de catálogos (F-09).
- No incluye: gestión de usuarios del sistema (C-05, Épica 1).

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Entregables de planeación | 2026-10-26 | F-01, F-05, F-06; brechas de DB acordadas (F-08) |
| Avance 25 % | 2026-11-04 | F-01 a F-09 |

## Decisiones pendientes

- Dónde se guarda el refresh token: `SeguridadDB` no tiene columna para él (F-03).
- Brechas en amarillo: G-06, G-07, G-12 y G-16 (F-08).

## Criterios de finalización

- [ ] F-01 a F-09 cerradas y aprobadas por QA
- [ ] `openapi.yaml` publicado con mock y aprobado por BE, FE y QA
- [ ] CI corre en cada pull request a `main`
- [ ] Base de pruebas con brechas aplicadas y semilla cargada
