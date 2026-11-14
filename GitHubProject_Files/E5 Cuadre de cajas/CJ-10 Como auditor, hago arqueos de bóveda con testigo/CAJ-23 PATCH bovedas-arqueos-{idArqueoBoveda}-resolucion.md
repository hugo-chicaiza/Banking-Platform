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
  "fechaHoraArqueo": "2026-11-16T10:00:00-05:00",
  "tipoArqueo": "Sorpresivo",
  "idUsuarioArqueador": 7,
  "idUsuarioTestigo": 9,
  "estado": "APROBADO",
  "idMovimientoAjuste": 1,
  "idsMovimientosAjuste": [
    1
  ],
  "diferenciaPorDenominacion": [
    {
      "idDenominacion": 1,
      "cantidad": -1
    }
  ],
  "observaciones": null,
  "saldoTeorico": 200,
  "saldoFisico": 180,
  "diferencia": -20,
  "idUsuarioAprobador": 9,
  "fechaHoraAprobacion": "2026-11-16T10:05:00-05:00"
}
```

## Errores

Formato ProblemDetails (ver F-04). Errores ampliados: ver la documentación de implementación enlazada al final.

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
