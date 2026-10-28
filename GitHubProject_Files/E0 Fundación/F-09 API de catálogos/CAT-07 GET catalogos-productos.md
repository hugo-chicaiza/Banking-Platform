---
number: 120
title: "CAT-07 | GET /api/v1/catalogos/productos"
type: api
code: CAT-07
parent: "[[F-09 API de catálogos]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/120
---

`GET /api/v1/catalogos/productos` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT07`

Lista los productos financieros, con filtro opcional por tipo. Lo usan A-01, emisión de tarjetas y CR-01.

| Lee | Escribe | DB |
|---|---|---|
| `ProductosFinancieros.Producto`, `ProductosFinancieros.Red` | — | — |

## Reglas de negocio

1. Solo `Estado = 'A'`. Sin `tipo` devuelve todos; con `tipo` solo los de ese tipo. Ordenados por `tipoProducto` y `nombreProducto`.
2. Campos que no aplican al tipo van en `null`: `montoAperturaMinimo` (Cuenta), `idTipoCredito` (Credito), `idRed` (Tarjeta, obligatorio por CHECK), `tipoCuenta` (Cuenta).
3. Montos en decimal.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| tipo | query | enum | No | `Cuenta` \| `Tarjeta` \| `Credito`; otro valor → 400 |

## Response `200`

```json
[ { "idProducto": 1, "codigoProducto": "AHO-01", "nombreProducto": "Ahorro a la vista", "tipoProducto": "Cuenta", "montoAperturaMinimo": 10.00, "idTipoCredito": null, "idRed": null, "tipoCuenta": "Ahorros", "permiteOperacionesPresenciales": true } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: sin filtro, cada tipo, tipo inválido, sin token

## Pendiente

- El contrato tiene `marca`; la DB usa `IdRed` → `ProductosFinancieros.Red` y agrega `TipoCuenta`. Actualizar el esquema `Producto` en `openapi.yaml`.
