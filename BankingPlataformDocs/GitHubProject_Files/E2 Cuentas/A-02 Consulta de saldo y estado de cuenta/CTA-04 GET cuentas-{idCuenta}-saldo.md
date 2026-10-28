---
number: 127
title: "CTA-04 | GET /api/v1/cuentas/{idCuenta}/saldo"
type: api
code: CTA-04
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/127
---

`GET /api/v1/cuentas/{idCuenta}/saldo` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** A-02 (#18) · **OpenAPI:** `CTA04`

Saldo contable, retenido y disponible.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta` | — | — |

## Reglas de negocio

1. `disponible = saldo - saldoRetenido`; montos en decimal.
2. Cuenta inexistente → 404. Una cuenta `Cerrada` devuelve saldos en 0.

## Flujo

1. El asesor accede a la sección de consulta de cuentas.
2. Busca la cuenta mediante `CTA-02`.
3. Selecciona la cuenta bancaria.
4. El frontend obtiene el identificador `idCuenta`.
5. Envía la solicitud `GET /api/v1/cuentas/{idCuenta}/saldo`.
6. El backend valida la autenticación y los permisos del usuario.
7. El sistema verifica que la cuenta exista.
8. Consulta el saldo contable y el saldo retenido registrados en `Cuentas.Cuenta`.
9. Calcula el saldo disponible.
10. Devuelve los tres saldos y la información necesaria para identificar la cuenta y su moneda.
11. El frontend presenta los resultados al asesor.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

## Response `200`

`SaldoCuenta`

```json
{
  "idCuenta": 501,
  "saldo": 1500.0,
  "saldoRetenido": 200.0,
  "saldoDisponible": 1300.0,
  "idMoneda": 840,
  "fechaConsulta": "2026-10-24T15:30:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
