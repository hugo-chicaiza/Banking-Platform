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
[ { "idProducto": 1, "codigoProducto": "AHO-01", "nombreProducto": "Ahorro a la vista", "tipoProducto": "Cuenta", "montoAperturaMinimo": 10.00, "idTipoCredito": null, "idRed": null, "tipoCuenta": "Ahorro", "permiteOperacionesPresenciales": true } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [x] Coincide con el OpenAPI generado por FastAPI (este checkout no contiene `openapi.yaml`).
- [x] Pruebas: sin filtro, cada tipo y tipo inválido.
- [ ] Sin token → 401 (depende de F-03; `require_auth()` aún no valida JWT).

## Implementación backend

- La consulta usa `ProductosFinancieros.Producto` y `ProductosFinancieros.Red`; expone `idRed` y `tipoCuenta` en lugar de `marca`.
- La DB mantiene `MontoAperturaMinimo` como NOT NULL; la API lo devuelve solo para `Cuenta` y `null` para los demás tipos. `idTipoCredito`, `idRed` y `tipoCuenta` también se proyectan según el tipo de producto.
- La prueba de integración requiere CooperativaDB configurada. La prueba sin token queda pendiente hasta completar F-03; este endpoint no debe considerarse listo para producción antes de validar JWT.
