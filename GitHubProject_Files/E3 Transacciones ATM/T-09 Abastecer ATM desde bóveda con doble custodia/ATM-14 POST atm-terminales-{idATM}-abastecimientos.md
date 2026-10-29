---
number: 152
title: "ATM-14 | POST /api/v1/atm/terminales/{idATM}/abastecimientos"
type: api
code: ATM-14
parent: "[[T-09 Abastecer ATM desde bóveda con doble custodia]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/152
---

`POST /api/v1/atm/terminales/{idATM}/abastecimientos` · **Roles:** SUPERVISOR, CAJERO · **Historia:** T-09 (#102) · **OpenAPI:** `ATM14`

Abastece gavetas desde una bóveda.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda`, `Boveda.BovedaDenominacion`, `ATM.Gaveta` | `Boveda.MovimientoBoveda`, `Boveda.MovimientoBovedaDenominacion`, `Boveda.BovedaDenominacion`, `Boveda.Boveda`, `ATM.Gaveta`, `ATM.GavetaMovimiento` | — |

## Reglas de negocio

1. Doble custodia: `autorizadoPor` distinto de quien registra → `409 DOBLE_CUSTODIA_VIOLADA`.
2. Por gaveta: `CantidadActual + cantidad` <= `Capacidad` → `422 GAVETA_SUPERA_CAPACIDAD`.
3. La bóveda (misma agencia) debe tener las piezas → `422 BOVEDA_SIN_DENOMINACION`.
4. Movimiento de bóveda `AbastecimientoATM` (egreso) + `GavetaMovimiento` por gaveta + asiento, en una transacción.

## Flujo

1. Validar custodia, capacidades y stock de la bóveda.
2. Registrar egreso de bóveda, ingresos a gavetas y asiento en una transacción.
3. Devolver el estado de las gavetas.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idATM | path | integer | Sí |  |

Body `AbastecimientoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idBoveda | integer | Sí |  |
| autorizadoPor | integer | Sí | Distinto del usuario que ejecuta |
| gavetas | AbastecimientoItem[] | Sí |  |
| observaciones | string | No |  |

```json
{
  "idBoveda": 1,
  "autorizadoPor": 12,
  "gavetas": [
    {
      "numeroGaveta": 1,
      "cantidad": 12
    }
  ],
  "observaciones": "observaciones"
}
```

## Response `201`

`array`

```json
[
  {
    "idGaveta": 1,
    "numeroGaveta": 1,
    "idDenominacion": 3,
    "capacidad": 1000,
    "cantidadActual": 100,
    "estado": "A"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `DOBLE_CUSTODIA_VIOLADA` | Quien autoriza es el mismo que opera |
| 422 | `GAVETA_SUPERA_CAPACIDAD` | La gaveta supera su capacidad |
| 422 | `BOVEDA_SIN_DENOMINACION` | La bóveda no tiene las piezas pedidas |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- acreditación de la segunda autorización, límites, gavetas repetidas y clave de idempotencia para reintentos.
