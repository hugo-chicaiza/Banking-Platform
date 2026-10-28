---
number: 79
title: "CRE-05 | POST /api/v1/creditos/buro/consultas"
type: api
code: CRE-05
parent: "[[CR-11 Consulta de buró de crédito]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3-4"
start_date: 2026-11-04
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/79
---

`POST /api/v1/creditos/buro/consultas` · **Roles:** ASESOR, SISTEMA · **Historia:** CR-11 (#69) · **OpenAPI:** `CRE05`

Consulta de buró (requiere consentimiento).

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.ReporteBuro` | — |

## Reglas de negocio

1. `consentimientoTitular` debe ser `true` (constraint de la DB) → `422 CONSENTIMIENTO_REQUERIDO`.
2. La integración con el buró es simulada; si el proveedor falla → `502 BURO_NO_DISPONIBLE` y no se guarda nada.
3. Guarda score y resumen; la solicitud (CRE-06) referencia el reporte.

## Flujo

1. Validar consentimiento.
2. Consultar el buró (simulado) y guardar `ReporteBuro`.
3. Responder 201 con score y resumen.

## Request

Body `BuroConsultaRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCliente | integer | Sí |  |
| consentimientoTitular | boolean | Sí | Debe ser true |

```json
{
  "idCliente": 1,
  "consentimientoTitular": true
}
```

## Response `201`

`ReporteBuro`

```json
{
  "idReporte": 1,
  "idCliente": 1,
  "score": 1,
  "diasMoraMaxima": 1,
  "operacionesCastigadas": 1,
  "deudaSistema": 100.0,
  "historialPositivo": 1,
  "historialFraude": true,
  "fechaConsulta": "2026-11-04T10:30:00Z"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `CONSENTIMIENTO_REQUERIDO` | No se aceptó el tratamiento de datos |
| 502 | `BURO_NO_DISPONIBLE` | El servicio de buró no responde |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
