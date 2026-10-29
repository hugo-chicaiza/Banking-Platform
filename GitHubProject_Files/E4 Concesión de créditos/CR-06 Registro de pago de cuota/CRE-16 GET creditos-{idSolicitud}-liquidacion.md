---
number: 90
title: "CRE-16 | GET /api/v1/creditos/{idSolicitud}/liquidacion"
type: api
code: CRE-16
parent: "[[CR-06 Registro de pago de cuota]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/90
---

`GET /api/v1/creditos/{idSolicitud}/liquidacion` · **Roles:** ASESOR, CAJERO · **Historia:** CR-06 (#34), también CR-09 · **OpenAPI:** `CRE16`

Cotiza el pago de una cuota o la cancelación total a una fecha.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoCuota`, `Credito.CreditoCuotaMora`, `Credito.TasaInteres` | — | — |

## Reglas de negocio

1. No persiste nada: cotiza a la `fecha` indicada (por defecto hoy).
2. Pago de cuota: la más antigua pendiente + su mora a la fecha. Cancelación total: capital pendiente + intereses al día + mora + seguros e impuestos devengados.
3. La mora usa `TasaNominalAnual + RecargoMoraSobreTasa` sobre el capital vencido por días.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |
| fecha | query | string | No | Default hoy |
| numeroCuota | query | integer | No | Cuota |
| cancelacionTotal | query | boolean | No | Cancelación total |

## Response `200`

`Liquidacion`

```json
{
  "fecha": "2026-11-04",
  "numeroCuota": 1,
  "capital": 150.0,
  "interes": 150.0,
  "totalSeguros": 150.0,
  "totalImpuestos": 150.0,
  "recargoMora": 150.0,
  "diasMora": 12,
  "totalAPagar": 150.0,
  "esCancelacionTotal": true
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
