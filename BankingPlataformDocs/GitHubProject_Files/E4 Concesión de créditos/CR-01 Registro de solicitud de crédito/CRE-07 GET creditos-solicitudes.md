---
number: 81
title: "CRE-07 | GET /api/v1/creditos/solicitudes"
type: api
code: CRE-07
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/81
---

`GET /api/v1/creditos/solicitudes` · **Roles:** ASESOR, APROBADOR, SUPERVISOR · **Historia:** CR-01 (#27), también CR-04 · **OpenAPI:** `CRE07`

Busca solicitudes.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoSolicitud` | — | — |

## Reglas de negocio

1. Filtros por estado, cliente, agencia y rango de fechas; paginado (máx. 100).
2. El aprobador usa `estado=REVISION_MANUAL` como bandeja de trabajo.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| estado | query | string | No | Estado |
| idCliente | query | integer | No | Cliente |
| idAgencia | query | string | No | Agencia |
| desde | query | string | No | Desde |
| hasta | query | string | No | Hasta |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageSolicitud`

```json
{
  "items": [
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
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
