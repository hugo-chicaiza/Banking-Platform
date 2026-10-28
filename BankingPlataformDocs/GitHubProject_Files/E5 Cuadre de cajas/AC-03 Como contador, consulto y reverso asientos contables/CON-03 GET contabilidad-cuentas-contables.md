---
number: 206
title: "CON-03 | GET /api/v1/contabilidad/cuentas-contables"
type: api
code: CON-03
parent: "[[AC-03 Como contador, consulto y reverso asientos contables]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/206
---

`GET /api/v1/contabilidad/cuentas-contables` · **Roles:** CONTADOR, AUDITOR, ADMIN · **Historia:** AC-03 (#67) · **OpenAPI:** `CON03`

Plan de cuentas (CUC).

| Lee | Escribe | DB |
|---|---|---|
| `Contabilidad.CuentasContables`, `Contabilidad.ElementoCUC` | — | — |

## Reglas de negocio

1. Plan de cuentas jerárquico; filtro por texto y por `imputable`. Solo las imputables reciben movimientos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| q | query | string | No | Código o nombre |
| imputable | query | boolean | No | Solo imputables |

## Response `200`

`array`

```json
[
  {
    "idCuentaContable": 1,
    "codigoCuenta": "COD01",
    "nombreCuenta": "nombreCuenta",
    "naturaleza": "DEUDORA",
    "tipoCuenta": "Ahorros",
    "idCuentaSuperior": 1,
    "esImputable": true,
    "saldo": 150.0,
    "estado": "Activo"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
