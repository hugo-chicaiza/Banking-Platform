---
number: 46
title: "Épica 4: Concesión de créditos"
type: epic
code: E4
parent: 
status: Épicas
priority: P1
size: 
estimate: 56
estimate_be: 
estimate_fe: 
etapa: "3-5"
start_date: 2026-11-04
target_date: 2026-11-23
state: open
labels: []
assignees: [davichocv18]
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/46
---

## Objetivo

Otorgar créditos de punta a punta: simular, evaluar con la política parametrizada, aprobar, desembolsar a la cuenta del cliente, cobrar cuotas y calcular mora.

## Alcance

- Incluye: simulación (CR-03), situación financiera (CR-10), buró (CR-11), solicitud y evaluación (CR-01, CR-02), revisión manual (CR-04), desembolso (CR-05), pagos (CR-06, CR-09), consultas (CR-07), mora (CR-08), garantes (CR-12), refinanciación (CR-13), documentos (CR-14), parámetros (CR-15).
- No incluye: integración real con un buró (es simulada).

## Hitos

| Hito | Fecha | Historias |
|---|---|---|
| Avance 50 % | 2026-11-09 | CR-01, CR-03, CR-10, CR-11 |
| Avance 75 % | 2026-11-16 | CR-02, CR-04 a CR-08, CR-12 |
| Avance 100 % | 2026-11-23 | CR-09, CR-13 a CR-15 (P3, solo si hay holgura) |

## Flujo

Simulación → situación financiera → buró → solicitud (se evalúa al crearla) → [revisión manual] → desembolso → pagos mensuales → mora diaria.

## Decisiones pendientes

- G-05: vista `vw_EstadoCredito` para el estado derivado del crédito.
- G-10: un pago en ventanilla siempre lleva la cuenta del cliente.
- Dónde se guardan los archivos de documentos (CR-14).

## Criterios de finalización

- [ ] Historias P1 cerradas y probadas
- [ ] Un crédito recorre simulación → aprobación → desembolso → pago → mora con asientos conciliados
