---
number: 84
title: "CRE-10 | POST /api/v1/creditos/solicitudes/{idSolicitud}/desistimiento"
type: api
code: CRE-10
parent: "[[CR-04 Aprobación o rechazo de solicitudes]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/84
---

`POST /api/v1/creditos/solicitudes/{idSolicitud}/desistimiento` · **Roles:** ASESOR · **Historia:** CR-04 (#30) · **OpenAPI:** `CRE10`

El cliente desiste de la solicitud.

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.CreditoSolicitud`, `Credito.CreditoSolicitudHistorialEstado` | — |

## Reglas de negocio

1. Solo `APROBADA` o `REVISION_MANUAL` pasan a `DESISTIDA`; si ya hay desembolso → `409 SOLICITUD_YA_DESEMBOLSADA`.
2. `motivo` obligatorio; queda en el historial.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `DesistimientoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| observacion | string | Sí |  |

```json
{
  "observacion": "string"
}
```

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

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `SOLICITUD_YA_DESEMBOLSADA` | La solicitud ya fue desembolsada |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
