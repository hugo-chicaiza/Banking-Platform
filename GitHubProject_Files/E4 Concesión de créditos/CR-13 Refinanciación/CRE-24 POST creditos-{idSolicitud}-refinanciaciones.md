---
number: 98
title: "CRE-24 | POST /api/v1/creditos/{idSolicitud}/refinanciaciones"
type: api
code: CRE-24
parent: "[[CR-13 Refinanciación]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/98
---

`POST /api/v1/creditos/{idSolicitud}/refinanciaciones` · **Roles:** SUPERVISOR · **Historia:** CR-13 (#71) · **OpenAPI:** `CRE24`

Refinancia el crédito (nueva versión de plan).

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.CreditoRefinanciacion`, `Credito.CreditoPlanAmortizacion`, `Credito.CreditoCuota`, `Credito.CreditoResumen` | — |

## Reglas de negocio

1. Solo créditos desembolsados y vigentes → `409 CREDITO_NO_REFINANCIABLE`.
2. Crea plan versión +1 con `MotivoVersion`, nuevas cuotas desde la versión vigente (DB 55003) y nuevo resumen; el plan anterior deja de ser vigente.
3. Registro `CreditoRefinanciacion` `VIGENTE`; supervisor del token.

## Flujo

1. Validar el crédito y calcular el nuevo plan con el saldo pendiente.
2. Cerrar el plan vigente y crear versión, cuotas, resumen y refinanciación en una transacción.
3. Responder 201 con el nuevo plan.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `RefinanciacionRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| nuevoPlazoMeses | integer | Sí |  |
| sistemaAmortizacion | FRANCES \| ALEMAN | No |  |
| motivo | string | Sí |  |

```json
{
  "nuevoPlazoMeses": 1,
  "sistemaAmortizacion": "FRANCES",
  "motivo": "string"
}
```

## Response `201`

`Refinanciacion`

```json
{
  "idRefinanciacion": 1,
  "montoRefinanciado": 150.0,
  "versionPlanNuevo": 12,
  "estado": "Activo",
  "plan": [
    {
      "numero": 1,
      "vencimiento": "2026-11-04",
      "saldoInicial": 150.0,
      "capital": 150.0,
      "interes": 150.0,
      "totalSeguros": 150.0,
      "totalImpuestos": 150.0,
      "valor": 150.0,
      "saldoFinal": 150.0
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CREDITO_NO_REFINANCIABLE` | El crédito no está vigente o no admite refinanciación |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
