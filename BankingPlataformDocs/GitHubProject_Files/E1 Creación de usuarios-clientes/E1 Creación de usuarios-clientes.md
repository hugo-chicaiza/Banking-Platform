---
number: 50
title: "Épica 1: Creación de usuarios/clientes"
type: epic
code: E1
parent: 
status: Épicas
priority: P1
size: 
estimate: 27
estimate_be: 
estimate_fe: 
etapa: "2-3"
start_date: 2026-10-26
target_date: 2026-11-09
state: open
labels: []
assignees: [hugo-chicaiza]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/50
---

## Objetivo

Registrar y mantener a los clientes (naturales y jurídicos) con su evaluación de riesgo, y administrar los usuarios internos que operan el sistema.

## Alcance

- Incluye: registro y validación de documento (C-01, C-02), búsqueda y perfil (C-03, C-06), edición y estados con auditoría (C-04), direcciones (C-07), riesgo LAFT/PEP (C-08), usuarios, roles y cajeros por agencia (C-05).
- No incluye: apertura de cuentas y tarjetas (Épica 2) ni créditos (Épica 4).

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Avance 25 % | 2026-11-04 | C-01 a C-05 |
| Avance 50 % | 2026-11-09 | C-06 a C-08 |

## Ciclo del cliente

`Pendiente` (al crear) → `Activo` cuando su evaluación de riesgo queda `Aprobado`; `Rechazado` → `Bloqueado`. Solo un cliente `Activo` abre cuentas (error DB 52001) y pide créditos.

## Decisiones pendientes

- Regla de productos vigentes para inactivar o eliminar un cliente (C-04).
- Contrato de usuarios: usar las tablas de `SeguridadDB` y agregar `cedula` a `UsuarioCreate` (C-05).

## Criterios de finalización

- [ ] C-01 a C-08 cerradas y aprobadas por QA
- [ ] Flujo completo probado: validar documento → registrar → evaluar riesgo → cliente Activo
