---
number: 28
title: "CR-02 | Evaluación de elegibilidad"
type: task
code: CR-02
parent: "[[E4 Concesión de créditos]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 4
estimate_fe: 0
etapa: "3-4"
start_date: 2026-11-04
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/28
---

> Como **sistema**, quiero **evaluar cada solicitud con la política parametrizada** para **aprobar automáticamente lo que cumple y derivar el resto**.

**Etapa:** 3-4 · **QA:** 0 d · **Tablas:** `Credito.ParametroPolitica`, `Credito.ReporteBuro`, `Credito.SituacionFinanciera`, `Credito.TasaInteres`

## Criterios de aceptación

- [ ] La evaluación usa `usp_EvaluarSolicitudCredito` y no se reimplementa en el backend
- [ ] Rechaza por producto, tasa, edad mínima, score o cuota sobre capacidad de pago, con motivo claro
- [ ] Deriva a REVISION_MANUAL si no hay buró o el monto supera `MONTO_REVISION_MANUAL`
- [ ] Los parámetros vigentes se pueden consultar (CRE-26)
- [ ] Pruebas: un caso por cada regla de rechazo y de revisión manual, y la aprobación automática

## Reglas de negocio

- Claves: `EDAD_MINIMA`, `SCORE_MINIMO`, `CUOTA_INGRESO_MAX`, `MONTO_REVISION_MANUAL`, `TASA_MAXIMA_<tipo>`, `VIGENCIA_APROBACION`.
- Más de una tasa vigente para el mismo caso es un error de datos (DB 55103).

## Dependencias

- Requiere: F-07 (cargar las claves), CR-01

## Pendiente

- G-12: confirmar con negocio los valores de cada clave antes de cargarlas en F-07.
