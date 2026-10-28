---
number: 40
title: "A-04 | Emisión de tarjeta de débito"
type: task
code: A-04
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P1
size: M
estimate: 4
estimate_be: 3
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/40
---

> Como **asesor**, quiero **emitir una tarjeta de débito asociada a una cuenta** para **que el cliente opere en ATM**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Tarjeta.Tarjeta`, `Tarjeta.BIN`, `Tarjeta.EnviosTarjeta`, `Tarjeta.TarjetaHis`, `Cuentas.Cuenta`

## Criterios de aceptación

- [ ] Emitir tarjeta para una cuenta `Activa` con producto de tipo Tarjeta y su BIN (TAR-01)
- [ ] El PAN nunca se guarda ni se muestra completo: solo token, máscara y hash
- [ ] Extensiones con tarjeta titular; envío opcional con dirección
- [ ] Buscar y ver tarjetas (TAR-02, TAR-03)
- [ ] Pruebas: cuenta no activa, producto incorrecto, BIN distinto, extensión sin titular, emisión correcta

## Reglas de negocio

- La tarjeta nace `Generada` y sin PIN; se activa en A-05.

## Dependencias

- Requiere: A-01
- Bloquea: A-05, T-01
