---
number: 124
title: "CTA-01 | POST /api/v1/cuentas"
type: api
code: CTA-01
parent: "[[A-01 Apertura de cuenta para un cliente]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/124
---

`POST /api/v1/cuentas` · **Roles:** ASESOR, ADMIN · **Historia:** A-01 (#2) · **OpenAPI:** `CTA01`

Abre una cuenta.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Cliente`, `Clientes.RiesgoCliente`, `ProductosFinancieros.Producto`, `ProductosFinancieros.SubProducto`, `Organizacion.Agencia` | `Cuentas.Cuenta` | `Cuentas.trg_Cuenta_ClienteActivo`, `Cuentas.usp_AbrirCuenta` |

## Reglas de negocio

1. Cliente `Activo` (riesgo aprobado) → si no, `409 CLIENTE_NO_ACTIVO` (DB 52001/52102); riesgo vigente `Rechazado` o antecedente que impide vinculación → `409 RIESGO_RECHAZADO`.
2. El producto y subproducto deben ser de tipo `Cuenta` y estar activos → `422 PRODUCTO_NO_ES_CUENTA` (DB 52103/52104).
3. El monto de apertura declarado debe cubrir `MontoAperturaMinimo` → 422 (DB 52105).
4. La cuenta nace `Activa` con `Saldo = 0`; el depósito de apertura se registra aparte en caja (CAJ-09).
5. `NumeroCuenta` lo genera el backend (único); `CreadoPor` sale del token; la agencia debe estar `A`.

## Flujo

1. Validar cliente, riesgo, producto y agencia.
2. Generar `NumeroCuenta` y ejecutar `Cuentas.usp_AbrirCuenta`.
3. Responder 201 con la cuenta; el FE pide al cajero el depósito de apertura.

## Request

Body `CuentaCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCliente | integer | Sí |  |
| idProducto | integer | Sí | Producto tipo Cuenta |
| idAgencia | string(3) | Sí |  |
| tipoCuenta | Ahorro \| Corriente | Sí |  |
| idMoneda | integer | No | Default 840 (USD) |

```json
{
  "idCliente": 125,
  "idProducto": 2,
  "idAgencia": "001",
  "tipoCuenta": "Ahorro",
  "idMoneda": 840
}
```

## Response `201`

`Cuenta`

```json
{
  "idCuenta": 501,
  "numeroCuenta": "AH000501",
  "idCliente": 125,
  "idProducto": 2,
  "tipoCuenta": "Ahorro",
  "saldo": 0.0,
  "saldoRetenido": 0.0,
  "estado": "PENDIENTE_ACTIVACION"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CLIENTE_NO_ACTIVO` | El cliente no está Activo (riesgo no aprobado) |
| 409 | `RIESGO_RECHAZADO` | Riesgo Rechazado o antecedente que impide vinculación |
| 422 | `PRODUCTO_NO_ES_CUENTA` | El producto no es de tipo Cuenta |
| 409 | `AGENCIA_INACTIVA` | La agencia no está activa |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- Formato de `NumeroCuenta` (brecha G-11 descartada: definir con negocio).
