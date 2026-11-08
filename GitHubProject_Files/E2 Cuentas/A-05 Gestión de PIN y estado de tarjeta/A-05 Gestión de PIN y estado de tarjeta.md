---
number: 59
title: "A-05 | PIN y estados de tarjeta"
type: task
code: A-05
parent: "[[E2 Cuentas]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/59
---

> Como **asesor**, quiero **aprobar, generar, bloquear o desbloquear tarjetas, con un PIN que se genera solo**, para **que el cliente use su tarjeta de forma segura sin que nadie del banco conozca su PIN**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Tarjeta.Tarjeta`, `Tarjeta.TransicionEstado`, `Tarjeta.TarjetaHis`, `Contabilidad.FechaContable` · `TarjetaPIN` (SeguridadDB)

## Ciclo de vida

```
Solicitada ─► Aprobada ─► Generada ─► Activa ◄─► Bloqueada / Inactiva
    │             │           │          │
    └─► Anulada ◄─┴───────────┘          └─► Cancelada / Vencida / Cerrada
```

| Paso | Quién | Qué pasa |
|---|---|---|
| Solicitada | Asesor, TAR-01 | Se registra la solicitud (`FechaSolicitud`), sin PIN |
| Aprobada | Asesor, TAR-04 | `FechaResolucion` y PIN generado automáticamente por el HSM |
| Anulada | Asesor, TAR-04 | Rechazo de la solicitud (`FechaResolucion`) o anulación antes de activar |
| Generada | Asesor, TAR-04 | Tarjeta física emitida (`FechaEmision`, `FechaExpiracion`) |
| Activa (débito) | Cliente, ATM-01 + ATM-06 | Primer cambio del PIN temporal en el ATM |
| Activa (crédito) | Automático | A los 3 días laborables desde `FechaEmision` |

## Criterios de aceptación

- [ ] Cambiar el estado solo según `Tarjeta.TransicionEstado` (TAR-04)
- [ ] Al aprobar, el PIN se genera automáticamente en el HSM; la API nunca recibe ni devuelve el PIN (TAR-04)
- [ ] Débito: PIN temporal (`RequiereCambio = 1`), entregado impreso con la tarjeta; la tarjeta se activa con el primer cambio de PIN en el ATM
- [ ] Crédito: PIN asignado sin entregarse (`RequiereCambio = 0`); la tarjeta se activa a los 3 días laborables
- [ ] `Generada → Activa` no se puede hacer a mano (`409 ACTIVACION_AUTOMATICA`)
- [ ] Regenerar el PIN (olvido o bloqueo por intentos) con TAR-05
- [ ] Ver el historial de eventos de la tarjeta (TAR-06)
- [ ] El PIN nunca aparece en logs, respuestas ni errores
- [ ] Pruebas: aprobación con PIN generado, transición válida e inválida, activación manual rechazada, regeneración de PIN

## Dependencias

- Requiere: A-04, F-08 (G-02 y estados de tarjeta)
- Bloquea: T-01, T-06

## Pendiente

- Proceso programado que active las tarjetas de crédito al cumplir los 3 días laborables (hoy se activan al usarse en ATM-01).
- Canal de entrega del PIN de débito (hoja impresa) y solicitud del PIN de crédito por servicio al cliente: no se simulan.
- G-02 y estados de tarjeta: ver F-08 (`TarjetaPIN.RequiereCambio`, `CK_Tarjeta_Estado`, `Tarjeta.TransicionEstado`).
