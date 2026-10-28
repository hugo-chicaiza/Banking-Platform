---
number: 172
title: "CAJ-15 | POST /api/v1/caja/jornadas/{idJornada}/devoluciones"
type: api
code: CAJ-14
parent: "[[CJ-06 Como cajero-supervisor, registro dotaciones adicionale]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/172
---

`POST /api/v1/caja/jornadas/{idJornada}/devoluciones` · **Roles:** CAJERO, SUPERVISOR · **Historia:** CJ-06 (#56) · **OpenAPI:** `CAJ15`

Devuelve efectivo a bóveda.

| Lee | Escribe | DB |
|---|---|---|
| `Caja.CuadreCaja`, `Caja.JornadasCaja`, `Boveda.Boveda` | `Boveda.MovimientoBoveda`, `Boveda.MovimientoBovedaDenominacion`, `Boveda.BovedaDenominacion`, `Boveda.Boveda`, `Caja.DevolucionesCaja`, `Caja.DevolucionCajaDenominacion` | `Caja.usp_RegistrarDevolucionCaja` |

## Reglas de negocio

1. Se ejecuta `Caja.usp_RegistrarDevolucionCaja`; no se reimplementa.
2. El cuadre debe tener conteo físico (DB 51111) y la devolución ser igual a lo contado (DB 51112); una sola por cuadre (DB 51113).
3. Doble custodia: quien recibe en bóveda no es el cajero → `409 DOBLE_CUSTODIA_VIOLADA` (DB 51106).
4. Devuelve la alerta `superaLimiteMaximo` (no bloquea).

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `DevolucionRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuadreCaja | integer | Sí |  |
| idBovedaDestino | integer | Sí |  |
| autorizadoPor | integer | Sí | Recibe en bóveda; distinto del cajero |
| desglose | Desglose[] | Sí |  |
| observacion | string(500) | No |  |

```json
{
  "idCuadreCaja": 1,
  "idBovedaDestino": 1,
  "autorizadoPor": 12,
  "desglose": [
    {
      "idDenominacion": 1,
      "cantidad": 12
    }
  ],
  "observacion": "Operación de prueba"
}
```

## Response `201`

`Devolucion`

```json
{
  "idDevolucionCaja": 1,
  "idJornadaCaja": 1,
  "idCuadreCaja": 1,
  "idBovedaDestino": 1,
  "monto": 150.0,
  "idMovimientoBoveda": 1,
  "superaLimiteMaximo": true
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- El procedimiento exige conteo antes de devolver, pero el contrato ordena devolución → conteo. Alinear el orden de CAJ-15 y CAJ-16 con el DBA (brecha G-09).
