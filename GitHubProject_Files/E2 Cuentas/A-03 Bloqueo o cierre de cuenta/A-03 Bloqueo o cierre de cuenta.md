---
number: 23
title: "A-03 | Bloqueo, inactivación y cierre de cuenta"
type: task
code: A-03
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P2
size: S
estimate: 2
estimate_be: 1
estimate_fe: 1
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/23
---

> Como **asesor**, quiero **bloquear, inactivar, reactivar o cerrar una cuenta** para **controlar su uso según el pedido del cliente o el riesgo**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Cuentas.Cuenta`, `Credito.CreditoDesembolso` y plan/cuotas/pagos/mora relacionados

## Criterios de aceptación

- [ ] Cambiar el estado con motivo según las transiciones permitidas (CTA-05)
- [ ] Cerrar exige saldo y retenido en 0 y sin desembolsos pendientes ni deuda vigente vinculada a su cuenta de desembolso; fija la fecha de cierre
- [ ] Una cuenta que no está `Activa` no puede debitarse
- [ ] El historial de movimientos se conserva tras el bloqueo o cierre
- [ ] Pruebas: cada transición válida, transición inválida, cierre con saldo, cierre con crédito

## Reglas de negocio

- Contrato público: ACTIVA ⇄ INACTIVA · ACTIVA → BLOQUEADA → ACTIVA · ACTIVA/INACTIVA → CERRADA (terminal).
- SQL Server persiste Activa, Inactiva, Bloqueada y Cerrada; el repositorio traduce los estados.
- La validación de créditos utiliza la relación real IdCuentaDesembolso. No existe un vínculo separado de garantía de cuenta en el esquema inspeccionado.
- Estado, saldo y relaciones se validan con bloqueos dentro de la transacción; FechaCierre usa el reloj SQL de Ecuador.
- No requiere modificaciones del esquema actual.

## Dependencias

- Requiere: A-01
