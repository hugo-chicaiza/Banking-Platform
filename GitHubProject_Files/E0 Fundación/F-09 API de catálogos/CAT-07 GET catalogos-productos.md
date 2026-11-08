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

Lista los productos financieros con sus subproductos, con filtro opcional por tipo de producto y por tipo de tarjeta. Lo usan A-01, emisión de tarjetas (TAR-01, con `tipoTarjeta`) y CR-01.

| Lee | Escribe | DB |
|---|---|---|
| `ProductosFinancieros.Producto`, `ProductosFinancieros.SubProducto`, `ProductosFinancieros.Red` | — | — |

## Reglas de negocio

1. Solo `Estado = 'A'`. Sin `tipo` devuelve todos; con `tipo` solo los de ese tipo. Ordenados por `tipoProducto` y `nombreProducto`.
2. Campos que no aplican al tipo van en `null`: `montoAperturaMinimo` (Cuenta), `idTipoCredito` (Credito), `idRed` (Tarjeta, obligatorio por CHECK), `tipoCuenta` (Cuenta).
3. Montos en decimal.
4. Cada producto trae `subproductos`: sus subproductos activos (`idSubProducto`, `codigoSubProducto`, `nombreSubProducto`), ordenados por nombre. Es lo que el asesor puede ofrecer del producto; con `tipo` solo salen los subproductos de ese tipo (p. ej. `tipo=Tarjeta` → Débito y Crédito Mastercard). Un producto sin subproductos activos trae `[]`.
5. Cada subproducto de tarjeta trae `tipoTarjeta` (`Debito` | `Credito`); en los demás va `null`. La base no tiene columna para el tipo: lo define el prefijo del código del subproducto, `TDB` = Débito y `TCR` = Crédito (convención de F-07, en `app/modules/catalogos/subproductos.py`).
6. `tipoTarjeta` filtra para que la emisión sea congruente: solo productos `Tarjeta` y, de cada uno, solo los subproductos de ese tipo; los productos sin subproductos de ese tipo no salen. Pensado para que el formulario de TAR-01 recargue las opciones al cambiar el tipo de tarjeta. Combinado con un `tipo` distinto de `Tarjeta` → `400 PARAMETRO_INVALIDO`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| tipo | query | enum | No | `Cuenta` \| `Tarjeta` \| `Credito`; otro valor → 400 |
| tipoTarjeta | query | enum | No | `Debito` \| `Credito`; implica `tipo=Tarjeta`; otro valor → 400 |

## Response `200`

```json
[
  {
    "idProducto": 4, "codigoProducto": "TAR001", "nombreProducto": "Tarjeta", "tipoProducto": "Tarjeta",
    "montoAperturaMinimo": null, "idTipoCredito": null, "idRed": 2, "tipoCuenta": null,
    "permiteOperacionesPresenciales": true,
    "subproductos": [
      { "idSubProducto": 6, "codigoSubProducto": "TCR001-MC", "nombreSubProducto": "Crédito Mastercard clásica", "tipoTarjeta": "Credito" },
      { "idSubProducto": 3, "codigoSubProducto": "TDB001-MC", "nombreSubProducto": "Débito Mastercard clásica", "tipoTarjeta": "Debito" }
    ]
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [x] Coincide con el OpenAPI que genera FastAPI (`/openapi.json`); el repo no tiene `openapi.yaml`
- [x] Prueba: sin filtro, cada tipo, tipo inválido
- [ ] Prueba sin token: depende de F-03, `require_auth` todavía no valida el JWT

## Implementación

- Devuelve `idRed` y `tipoCuenta` en lugar de `marca`. Cuando exista `openapi.yaml`, su esquema `Producto` debe reflejarlo.
- `MontoAperturaMinimo` es NOT NULL en la BD, pero la API solo lo devuelve en productos `Cuenta`; en los demás tipos va `null`.
- Un `tipo` fuera de la lista responde 400 `DATOS_INVALIDOS`; si se repite `tipo` o llega otro parámetro, 400 `PARAMETRO_INVALIDO` (formato F-04).
