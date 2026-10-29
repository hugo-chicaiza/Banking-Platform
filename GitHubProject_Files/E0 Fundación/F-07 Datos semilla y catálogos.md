---
number: 107
title: "F-07 | Datos semilla y catálogos"
type: task
code: F-07
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 3
estimate_fe: 
etapa: "1-2"
start_date: 2026-10-19
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/107
---

> Como **equipo**, quiero **cargar datos semilla y catálogos** para **poder probar cualquier flujo de punta a punta**.

**Etapa:** 1-2 · **QA:** 1 d · **Tablas:** `Catalogo.*`, `Caja.TipoMovimientoCaja`, `Contabilidad.*`, `Credito.TasaInteres`, `Credito.ParametroPolitica`, `Organizacion.Agencia`, `Organizacion.Usuarios`

## Criterios de aceptación

- [ ] Scripts versionados e idempotentes (re-ejecutables sin duplicar)
- [ ] Cargan: canales, códigos de respuesta, denominaciones, tipos de movimiento de caja, tipos de asiento, plan de cuentas CUC, calendario contable, comisiones, tasas y parámetros de política
- [ ] Un usuario de prueba por rol, con contraseñas ficticias
- [ ] Respetan las restricciones de la DB (Denominacion única por tipo y valor; canal con PIN exige tarjeta)
- [ ] QA ejecuta al menos un flujo completo por módulo con la semilla
- [ ] Guía de orden de ejecución y reinicio de la base

## Dependencias

- Requiere: F-08 (esquema final), G-12 (claves de política)
- Bloquea: F-06, F-09 y las pruebas de todos los módulos
