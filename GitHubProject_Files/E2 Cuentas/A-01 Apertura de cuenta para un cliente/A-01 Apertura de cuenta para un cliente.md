---
number: 2
title: "A-01 | Apertura de cuenta"
type: task
code: A-01
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P1
size: L
estimate: 5
estimate_be: 3
estimate_fe: 2
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/2
---

> Como **asesor**, quiero **abrir una cuenta de ahorro o corriente a un cliente activo** para **que pueda operar con la cooperativa**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Cuentas.Cuenta`, `ProductosFinancieros.Producto`, `ProductosFinancieros.SubProducto`, `Clientes.Cliente`, `Clientes.RiesgoCliente`

## Criterios de aceptación

- [ ] Solo clientes `Activo` sin riesgo rechazado abren cuenta (CTA-01)
- [ ] Se elige producto/subproducto de tipo Cuenta y agencia activa
- [ ] El número de cuenta se genera solo y es único
- [ ] La cuenta nace `Activa` con saldo 0; el depósito de apertura se hace en caja y debe cubrir el mínimo del producto
- [ ] Pruebas: cliente Pendiente o Bloqueado, producto que no es cuenta, monto bajo el mínimo, apertura correcta

## Reglas de negocio

- `Cuentas.usp_AbrirCuenta` valida cliente (52101/52102), subproducto (52103/52104) y monto mínimo (52105).

## Dependencias

- Requiere: C-01, C-08
- Bloquea: A-04, CJ-07
