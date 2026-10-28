---
number: 83
title: "CRE-09 | POST /api/v1/creditos/solicitudes/{idSolicitud}/resolucion"
type: api
code: CRE-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/83
---

`POST /api/v1/creditos/solicitudes/{idSolicitud}/resolucion` · **Roles:** APROBADOR · **Historia:** CR-04 (#30) · **OpenAPI:** `CRE09`

Aprueba o rechaza una solicitud en REVISION_MANUAL.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoSolicitud` | `Credito.CreditoSolicitud`, `Credito.CreditoSolicitudHistorialEstado` | — |

## Reglas de negocio

1. Solo solicitudes en `REVISION_MANUAL` → `409 SOLICITUD_NO_EN_REVISION`.
2. El aprobador no puede ser quien creó la solicitud → `403 APROBADOR_IGUAL_CREADOR`.
3. `decision` APROBADA o RECHAZADA con `observacion` obligatoria; fija `TipoRevision = Manual`, `AprobadoPor` (token) y `FechaResolucion`.
4. Aprobar exige `DeclaraLicitudFondos = 1` (CHECK de la DB).

## Flujo

1. Validar estado y separación de funciones.
2. Actualizar la solicitud e insertar el historial en una transacción.
3. Responder 200 con la solicitud.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `ResolucionSolicitud`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| decision | APROBAR \| RECHAZAR | Sí |  |
| observacion | string | Sí |  |

```json
{
  "decision": "APROBAR",
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
| 409 | `SOLICITUD_NO_EN_REVISION` | La solicitud no está en REVISION_MANUAL |
| 403 | `APROBADOR_IGUAL_CREADOR` | Quien aprueba es quien creó la solicitud |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- G-04 se descartó: el historial solo guarda `Observacion`, así que el texto debe decir el estado anterior y el nuevo.
