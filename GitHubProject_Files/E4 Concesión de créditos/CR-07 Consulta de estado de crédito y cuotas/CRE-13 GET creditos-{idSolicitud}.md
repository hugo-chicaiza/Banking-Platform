---
number: 87
title: "CRE-13 | GET /api/v1/creditos/{idSolicitud}"
type: api
code: CRE-13
parent: "[[CR-07 Consulta de estado de crédito y cuotas]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/87
---

`GET /api/v1/creditos/{idSolicitud}` · **Roles:** ASESOR, CAJERO, SUPERVISOR · **Historia:** CR-07 (#35) · **OpenAPI:** `CRE13`

Estado del crédito (resumen).

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoDesembolso`, `Credito.CreditoResumen`, `Credito.CreditoCuota` | — | — |

## Reglas de negocio

1. Estado derivado: EN_TRAMITE, VIGENTE, EN_MORA, CANCELADO o RECHAZADO (no está en la DB; se calcula de solicitud, cuotas y mora).
2. Incluye saldo de capital, cuotas pagadas y pendientes, próxima cuota y mora.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

## Response `200`

`Credito`

```json
{
  "idSolicitud": 1,
  "numeroSolicitud": "string",
  "estadoSolicitud": "string",
  "estadoCredito": "EN_TRAMITE",
  "montoDesembolsado": 100.0,
  "saldoCapital": 100.0,
  "numeroTotalCuotas": 1,
  "cuotasPagadas": 1,
  "cuotasVencidas": 1,
  "proximoVencimiento": "2026-11-04",
  "versionPlanVigente": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- G-05 (aplicar): crear la vista `Credito.vw_EstadoCredito` para no repetir el cálculo.
