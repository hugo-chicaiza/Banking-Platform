---
number: 93
title: "CRE-19 | POST /api/v1/creditos/mora/calculos"
type: api
code: CRE-19
parent: "[[CR-08 Cálculo de mora e interés por vencimiento]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4-5"
start_date: 2026-11-09
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/93
---

`POST /api/v1/creditos/mora/calculos` · **Roles:** SISTEMA, ADMIN · **Historia:** CR-08 (#36) · **OpenAPI:** `CRE19`

Ejecuta el cálculo diario de mora (proceso batch).

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoCuota`, `Credito.TasaInteres` | `Credito.CreditoCuotaMora`, `Credito.CreditoCuota` | — |

## Reglas de negocio

1. Proceso diario: una ejecución por fecha → `409 CALCULO_YA_EJECUTADO`.
2. Las cuotas `PENDIENTE` con vencimiento pasado pasan a `VENCIDA` y se registra `CreditoCuotaMora` (días = fin - inicio).
3. Idempotente por fecha; lo invoca un job o un ADMIN.

## Flujo

1. Bloquear la fecha de cálculo.
2. Marcar cuotas vencidas y calcular mora en una transacción.
3. Responder 200 con totales procesados.

## Request

Body `MoraCalculoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| fechaCalculo | string | Sí |  |

```json
{
  "fechaCalculo": "2026-11-04"
}
```

## Response `202`

`MoraCalculoResultado`

```json
{
  "fechaCalculo": "2026-11-04",
  "cuotasEvaluadas": 1,
  "cuotasMarcadasVencidas": 1,
  "recargoTotal": 100.0
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CALCULO_YA_EJECUTADO` | La mora de esa fecha ya fue calculada |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
