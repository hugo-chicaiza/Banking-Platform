---
number: 82
title: "CRE-08 | GET /api/v1/creditos/solicitudes/{idSolicitud}"
type: api
code: CRE-08
parent: "[[CR-01 Registro de solicitud de crédito]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/82
---

`GET /api/v1/creditos/solicitudes/{idSolicitud}` · **Roles:** ASESOR, APROBADOR, SUPERVISOR · **Historia:** CR-01 (#27) · **OpenAPI:** `CRE08`

Detalle de la solicitud.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoSolicitud`, `Credito.CreditoGarante` | — | — |

## Reglas de negocio

1. Incluye garantes, reporte de buró y situación financiera usados. Inexistente → 404.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

## Response `200`

`Solicitud`

```json
{
  "idSolicitud": 1,
  "numeroSolicitud": "numeroSolicitud",
  "idCliente": 1,
  "idTipoCredito": 1,
  "idProducto": 1,
  "idAgencia": "001",
  "monto": 150.0,
  "plazoMeses": 12,
  "sistemaAmortizacion": "sistemaAmortizacion",
  "tasaNominalAnual": 0.12,
  "cuotaReferencial": 150.0,
  "totalIntereses": 150.0,
  "totalSeguros": 150.0,
  "totalImpuestos": 150.0,
  "capacidadPago": 150.0,
  "estado": "APROBADA",
  "tipoRevision": "Manual",
  "motivosEvaluacion": [
    "motivosEvaluacion"
  ],
  "fechaSolicitud": "2026-11-04",
  "fechaResolucion": "2026-11-04T10:15:00-05:00",
  "aprobadoPor": 12,
  "creadoPor": 12,
  "observaciones": "observaciones",
  "idGarante": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
