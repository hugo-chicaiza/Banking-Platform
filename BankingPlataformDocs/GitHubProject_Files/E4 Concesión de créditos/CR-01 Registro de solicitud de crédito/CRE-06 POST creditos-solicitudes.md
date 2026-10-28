---
number: 80
title: "CRE-06 | POST /api/v1/creditos/solicitudes"
type: api
code: CRE-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/80
---

`POST /api/v1/creditos/solicitudes` · **Roles:** ASESOR · **Historia:** CR-01 (#27), también CR-02 · **OpenAPI:** `CRE06`

Crea y evalúa la solicitud de crédito.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Cliente`, `Clientes.RiesgoCliente`, `Credito.SituacionFinanciera`, `Credito.ReporteBuro`, `Credito.ParametroPolitica`, `Credito.TasaInteres`, `ProductosFinancieros.Producto` | `Credito.CreditoSolicitud`, `Credito.CreditoSolicitudHistorialEstado`, `Credito.CreditoGarante` | `Credito.usp_EvaluarSolicitudCredito` |

## Reglas de negocio

1. Requisitos: cliente `Activo` sin riesgo rechazado → `409 CLIENTE_NO_ACTIVO`; situación financiera vigente → `422 SITUACION_FINANCIERA_REQUERIDA`; `consienteConsultaBuro` y `declaraLicitudFondos` en `true` → `422 CONSENTIMIENTO_REQUERIDO`.
2. Monto y plazo dentro de la tasa vigente → `422 MONTO_FUERA_DE_RANGO` o `422 PLAZO_SUPERA_MAXIMO`.
3. La solicitud se inserta en `REVISION_MANUAL` y se evalúa en el acto con `usp_EvaluarSolicitudCredito`: producto del tipo, tasa vigente y `TASA_MAXIMA_<tipo>`, `EDAD_MINIMA`, `SCORE_MINIMO`, `CUOTA_INGRESO_MAX` y `MONTO_REVISION_MANUAL`.
4. Resultado: `APROBADA` (automática), `RECHAZADA` (con motivo) o queda en `REVISION_MANUAL` (sin buró o monto alto). No existe estado 'en evaluación'.
5. `CreadoPor` sale del token; el historial guarda el resultado y el motivo.

## Flujo

1. Validar requisitos y calcular la cuota referencial.
2. Insertar la solicitud (y sus garantes, si vienen) en `REVISION_MANUAL`.
3. Ejecutar `usp_EvaluarSolicitudCredito` con `@Aplicar = 1`.
4. Responder 201 con el estado final y `motivosEvaluacion`.

## Request

Body `SolicitudCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCliente | integer | Sí |  |
| idTipoCredito | integer | Sí |  |
| idProducto | integer | Sí | Producto tipo Credito |
| idAgencia | string(3) | Sí |  |
| idCanal | integer | Sí |  |
| idSituacion | integer | Sí |  |
| monto | number | Sí |  |
| plazoMeses | integer | Sí |  |
| sistemaAmortizacion | FRANCES \| ALEMAN | Sí |  |
| consienteConsultaBuro | boolean | Sí | Debe ser true |
| declaraLicitudFondos | boolean | Sí | Debe ser true |
| idGarante | integer | No |  |
| observaciones | string(500) | No |  |

```json
{
  "idCliente": 1,
  "idTipoCredito": 1,
  "idProducto": 1,
  "idAgencia": "string",
  "idCanal": 1,
  "idSituacion": 1,
  "monto": 100.0,
  "plazoMeses": 1,
  "sistemaAmortizacion": "FRANCES",
  "consienteConsultaBuro": true,
  "declaraLicitudFondos": true,
  "idGarante": 1,
  "observaciones": "string"
}
```

## Response `201`

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
| 409 | `CLIENTE_NO_ACTIVO` | El cliente no está Activo (riesgo no aprobado) |
| 409 | `RIESGO_RECHAZADO` | Riesgo Rechazado o antecedente que impide vinculación |
| 422 | `SITUACION_FINANCIERA_REQUERIDA` | Falta la situación financiera vigente |
| 422 | `CONSENTIMIENTO_REQUERIDO` | No se aceptó el tratamiento de datos |
| 422 | `MONTO_FUERA_DE_RANGO` | El monto está fuera del rango de la tasa vigente |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
