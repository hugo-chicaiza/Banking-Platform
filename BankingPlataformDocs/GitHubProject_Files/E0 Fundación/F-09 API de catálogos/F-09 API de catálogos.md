---
number: 109
title: "F-09 | API de catálogos"
type: task
code: F-09
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/109
---

> Como **usuario del sistema**, quiero **listas de catálogos en los formularios** para **elegir valores válidos en lugar de escribirlos**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Catalogo.*`, `Organizacion.Agencia`, `ProductosFinancieros.Producto`, `Canal.Canal`, `Credito.TipoCredito`, `Caja.TipoMovimientoCaja`

## Criterios de aceptación

- [ ] CAT-01 a CAT-10 responden según `openapi.yaml` y exigen token (401 sin token)
- [ ] Si la tabla tiene `Estado`, solo registros activos; agencias devuelven su estado
- [ ] FE: servicio de catálogos con caché por sesión
- [ ] Los formularios de clientes, cuentas, créditos y caja usan estos catálogos
- [ ] Pruebas: con datos, lista vacía, filtro de productos por tipo, sin token

## Reglas de negocio

- Los catálogos son de solo lectura en la API; se mantienen por semilla (F-07).

## Dependencias

- Requiere: F-03, F-07
- Bloquea: Épicas 1, 2, 4 y 5 (formularios)

## Pendiente

- CAT-09 (#74) cuelga hoy de CR-03; moverlo a esta historia.
