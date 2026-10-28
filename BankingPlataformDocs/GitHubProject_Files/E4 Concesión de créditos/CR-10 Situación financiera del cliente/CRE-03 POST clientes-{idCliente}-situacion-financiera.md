---
number: 77
title: "CRE-03 | POST /api/v1/clientes/{idCliente}/situacion-financiera"
type: api
code: CRE-03
parent: "[[CR-10 Situación financiera del cliente]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/77
---

`POST /api/v1/clientes/{idCliente}/situacion-financiera` · **Roles:** ASESOR, ADMIN · **Historia:** CR-10 (#68) · **OpenAPI:** `CRE03`

Registra la situación financiera (marca la anterior como no vigente).

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.SituacionFinanciera` | — |

## Reglas de negocio

1. El cliente debe existir y no estar `Eliminado` ni `Bloqueado`.
2. Ingresos, gastos y deudas >= 0; `capacidadPago = ingresoMensual - gastoMensual - cuotaDeudaExterna`.
3. La nueva queda vigente y la anterior pasa a no vigente en la misma transacción.

## Flujo

1. Validar cliente y montos.
2. Desmarcar la vigente e insertar la nueva en una transacción.
3. Responder 201.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

Body `SituacionFinancieraCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| relacionLaboral | DEPENDIENTE \| INDEPENDIENTE \| EMPRESARIAL | Sí |  |
| antiguedadLaboralMeses | integer | Sí |  |
| ingresoMensual | number | Sí | > 0 |
| gastoMensual | number | Sí |  |
| cuotaDeudaExterna | number | No |  |
| ingresosAnuales | number | No |  |
| patrimonioNeto | number | No |  |
| ingresosDeclarados | number | No |  |

```json
{
  "relacionLaboral": "DEPENDIENTE",
  "antiguedadLaboralMeses": 12,
  "ingresoMensual": 150.0,
  "gastoMensual": 150.0,
  "cuotaDeudaExterna": 150.0,
  "ingresosAnuales": 150.0,
  "patrimonioNeto": 150.0,
  "ingresosDeclarados": 150.0
}
```

## Response `201`

`SituacionFinanciera`

```json
{
  "idSituacion": 1,
  "idCliente": 1,
  "relacionLaboral": "relacionLaboral",
  "antiguedadLaboralMeses": 12,
  "ingresoMensual": 150.0,
  "gastoMensual": 150.0,
  "cuotaDeudaExterna": 150.0,
  "esVigente": true,
  "fechaDeclaracion": "2026-11-04T10:15:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
