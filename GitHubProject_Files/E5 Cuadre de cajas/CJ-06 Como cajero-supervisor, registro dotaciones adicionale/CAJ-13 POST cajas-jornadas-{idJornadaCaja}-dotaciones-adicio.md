---
number: 171
title: "CAJ-07 | POST /api/v1/caja/jornadas/{idJornada}/dotaciones"
type: api
code: CAJ-13
parent: "[[CJ-01 Como cajero, abro jornada de caja con dotación INICIAL]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/171
---

`POST /api/v1/caja/jornadas/{idJornada}/dotaciones` · **Roles:** CAJERO, SUPERVISOR · **Historia:** CJ-01 (#51), también CJ-06 · **OpenAPI:** `CAJ07`

Registra dotación desde bóveda (INICIAL o ADICIONAL).

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.Boveda`, `Boveda.BovedaDenominacion`, `Catalogo.Denominacion` | `Boveda.MovimientoBoveda`, `Boveda.MovimientoBovedaDenominacion`, `Boveda.BovedaDenominacion`, `Boveda.Boveda`, `Caja.DotacionesCaja`, `Caja.DotacionCajaDenominacion` | `Caja.usp_RegistrarDotacionCaja` |

## Reglas de negocio

1. Se ejecuta `Caja.usp_RegistrarDotacionCaja`; no se reimplementa.
2. INICIAL una sola vez e igual a `DineroInicial` (DB 51008, 51010); ADICIONAL solo después de la INICIAL (DB 51009).
3. Doble custodia: quien autoriza no es el cajero → `409 DOBLE_CUSTODIA_VIOLADA` (DB 51007).
4. Bóveda activa y de la misma agencia (DB 51011-51013); saldo y piezas suficientes (DB 51014, 51015); desglose válido (DB 51002-51004).
5. Devuelve la alerta `bovedaBajoMinimo` (no bloquea).

## Flujo

1. Validar la jornada `ABIERTA` (DB 51006).
2. Ejecutar el procedimiento con el desglose en JSON (`[{IdDenominacion, Cantidad}]`).
3. Responder 201 con la dotación y la alerta.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idJornada | path | integer | Sí |  |

Body `DotacionRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idBoveda | integer | Sí |  |
| autorizadoPor | integer | Sí | Distinto del cajero (doble custodia) |
| tipoDotacion | INICIAL \| ADICIONAL | Sí |  |
| desglose | Desglose[] | Sí |  |
| observacion | string(500) | No |  |

```json
{
  "idBoveda": 1,
  "autorizadoPor": 12,
  "tipoDotacion": "INICIAL",
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

`Dotacion`

```json
{
  "idDotacionCaja": 1,
  "idJornadaCaja": 1,
  "idBoveda": 1,
  "tipoDotacion": "tipoDotacion",
  "monto": 150.0,
  "idMovimientoBoveda": 1,
  "bovedaBajoMinimo": true,
  "estado": "Activo"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)

## Pendiente

- Hoy el autorizador llega en el body; se recomienda que se autentique (token de autorización del SUPERVISOR).
