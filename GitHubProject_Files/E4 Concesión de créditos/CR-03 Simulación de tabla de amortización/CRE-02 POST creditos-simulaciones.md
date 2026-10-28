---
number: 76
title: "CRE-02 | POST /api/v1/creditos/simulaciones"
type: api
code: CRE-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/76
---

`POST /api/v1/creditos/simulaciones` · **Roles:** ASESOR, ADMIN · **Historia:** CR-03 (#29) · **OpenAPI:** `CRE02`

Simula la tabla de amortización (no persiste).

| Lee | Escribe | DB |
|---|---|---|
| `Credito.TasaInteres`, `Credito.Seguro`, `Credito.Impuesto`, `Credito.TipoCreditoSeguro`, `Credito.TipoCreditoImpuesto` | — | — |

## Reglas de negocio

1. No persiste nada.
2. Monto fuera del rango de `TasaInteres` → `422 MONTO_FUERA_DE_RANGO`; plazo mayor a `PlazoMaximoMeses` → `422 PLAZO_SUPERA_MAXIMO`.
3. FRANCES = cuota fija; ALEMAN = capital fijo. Cada cuota suma capital, interés, seguros e impuestos; montos en decimal redondeados a 2.
4. Devuelve totales (intereses, seguros, impuestos, costo total) y el plan cuota por cuota.

## Flujo

1. Obtener tasa, seguros e impuestos vigentes (como CRE-01).
2. Calcular el plan según el sistema de amortización.
3. Responder 200 con totales y plan.

## Request

Body `SimulacionRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idTipoCredito | integer | Sí |  |
| monto | number | Sí |  |
| plazoMeses | integer | Sí |  |
| sistemaAmortizacion | FRANCES \| ALEMAN | Sí |  |
| fechaPrimerVencimiento | string | No |  |

```json
{
  "idTipoCredito": 1,
  "monto": 100.0,
  "plazoMeses": 1,
  "sistemaAmortizacion": "FRANCES",
  "fechaPrimerVencimiento": "2026-11-04"
}
```

## Response `200`

`Simulacion`

```json
{
  "tasaNominalAnual": 0.12,
  "cuotaReferencial": 150.0,
  "totalIntereses": 150.0,
  "totalSeguros": 150.0,
  "totalImpuestos": 150.0,
  "costoTotal": 150.0,
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
| 422 | `MONTO_FUERA_DE_RANGO` | El monto está fuera del rango de la tasa vigente |
| 422 | `PLAZO_SUPERA_MAXIMO` | El plazo supera el máximo de la tasa vigente |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
