---
number: 126
title: "CTA-03 | GET /api/v1/cuentas/{idCuenta}"
type: api
code: CTA-03
parent: "[[A-02 Consulta de saldo y estado de cuenta]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/126
---

`GET /api/v1/cuentas/{idCuenta}` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** A-02 (#18) · **OpenAPI:** `CTA03`

Detalle de cuenta.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta` | — | — |

## Reglas de negocio

1. Cuenta inexistente → 404.

## Flujo

1. El asesor accede a la sección de consulta de cuentas.
2. Busca la cuenta mediante `CTA-02`.
3. Selecciona la cuenta que desea consultar.
4. El frontend obtiene el identificador `idCuenta`.
5. El frontend envía la solicitud `GET /api/v1/cuentas/{idCuenta}`.
6. El backend valida la autenticación y los permisos del usuario.
7. El sistema verifica que la cuenta exista.
8. El backend consulta la información registrada en `Cuentas.Cuenta`.
9. El sistema devuelve los datos generales y el estado actual de la cuenta.
10. El frontend presenta la información al asesor.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

## Response `200`

`Cuenta`

```json
{
  "idCuenta": 501,
  "numeroCuenta": "AH000501",
  "idCliente": 125,
  "idProducto": 2,
  "idAgencia": "001",
  "tipoCuenta": "Ahorro",
  "idMoneda": 840,
  "saldo": 1500.0,
  "saldoRetenido": 200.0,
  "estado": "ACTIVA"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
