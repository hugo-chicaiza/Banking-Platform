---
number: 75
title: "CRE-01 | GET /api/v1/creditos/tipos/{idTipoCredito}/condiciones"
type: api
code: CRE-01
parent: "[[CR-03 Simulación de tabla de amortización]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/75
---

`GET /api/v1/creditos/tipos/{idTipoCredito}/condiciones` · **Roles:** ASESOR, ADMIN · **Historia:** CR-03 (#29) · **OpenAPI:** `CRE01`

Tasa, plazo máximo, seguros e impuestos vigentes.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.TasaInteres`, `Credito.TipoCreditoSeguro`, `Credito.Seguro`, `Credito.TipoCreditoImpuesto`, `Credito.Impuesto` | — | — |

## Reglas de negocio

1. Devuelve la tasa vigente para el tipo, monto y plazo, el plazo máximo, y los seguros e impuestos activos del tipo.
2. Sin tasa vigente para ese monto y plazo → 404; más de una tasa vigente es un error de datos (DB 55103) → 500 y alerta.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTipoCredito | path | integer | Sí |  |
| monto | query | number | No | Monto |
| plazoMeses | query | integer | No | Plazo |

## Response `200`

`CondicionesCredito`

```json
{
  "idTipoCredito": 1,
  "tasaNominalAnual": 0.12,
  "plazoMaximoMeses": 12,
  "recargoMoraSobreTasa": 0.12,
  "montoMinimo": 150.0,
  "montoMaximo": 150.0,
  "seguros": [
    {
      "id": 1,
      "codigo": "COD01",
      "nombre": "María López",
      "tipoCalculo": "Porcentaje",
      "valor": 150.0,
      "obligatorio": true
    }
  ],
  "impuestos": [
    {
      "id": 1,
      "codigo": "COD01",
      "nombre": "María López",
      "tipoCalculo": "Porcentaje",
      "valor": 150.0,
      "obligatorio": true
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
