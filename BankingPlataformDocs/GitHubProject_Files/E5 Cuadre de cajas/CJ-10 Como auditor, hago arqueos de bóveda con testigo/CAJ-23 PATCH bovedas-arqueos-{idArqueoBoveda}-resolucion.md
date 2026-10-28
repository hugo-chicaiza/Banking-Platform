---
number: 181
title: "BOV-06 | POST /api/v1/boveda/arqueos/{idArqueoBoveda}/aprobacion"
type: api
code: CAJ-23
parent: "[[CJ-10 Como auditor, hago arqueos de bóveda con testigo]]"
status: Backlog
priority: P3
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/181
---

`POST /api/v1/boveda/arqueos/{idArqueoBoveda}/aprobacion` · **Roles:** SUPERVISOR · **Historia:** CJ-10 (#64) · **OpenAPI:** `BOV06`

Aprueba arqueo y genera ajuste si hay diferencia.

| Lee | Escribe | DB |
|---|---|---|
| — | `Boveda.ArqueoBoveda`, `Boveda.MovimientoBoveda` | — |

## Reglas de negocio

1. Solo arqueos `REGISTRADO`; pasa a `APROBADO`. El aprobador no es el arqueador.
2. Si hay diferencia, genera el movimiento `AjusteFaltante` o `AjusteSobrante` con su asiento en la misma transacción.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idArqueoBoveda | path | integer | Sí |  |

## Response `200`

`ArqueoBoveda`

```json
{
  "idArqueoBoveda": 1,
  "idBoveda": 1,
  "fechaHoraArqueo": "2026-11-04T10:15:00-05:00",
  "tipoArqueo": "tipoArqueo",
  "idUsuarioArqueador": 1,
  "idUsuarioTestigo": 1,
  "estado": "REGISTRADO",
  "idMovimientoAjuste": 1,
  "diferenciaPorDenominacion": [
    {
      "idDenominacion": 1,
      "cantidad": 12
    }
  ],
  "observaciones": "observaciones"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
