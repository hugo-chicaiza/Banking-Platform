---
number: 180
title: "BOV-05 | POST /api/v1/boveda/bovedas/{idBoveda}/arqueos"
type: api
code: CAJ-22
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/180
---

`POST /api/v1/boveda/bovedas/{idBoveda}/arqueos` · **Roles:** SUPERVISOR, AUDITOR · **Historia:** CJ-10 (#64) · **OpenAPI:** `BOV05`

Registra un arqueo con testigo.

| Lee | Escribe | DB |
|---|---|---|
| `Boveda.BovedaDenominacion` | `Boveda.ArqueoBoveda`, `Boveda.ArqueoBovedaDenominacion` | — |

## Reglas de negocio

1. Arqueador y testigo distintos → `409 ARQUEADOR_IGUAL_TESTIGO`.
2. Registra el conteo por denominación y la diferencia contra `BovedaDenominacion`; nace `REGISTRADO`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idBoveda | path | integer | Sí |  |

Body `ArqueoBovedaRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoArqueo | Sorpresivo \| Programado | Sí |  |
| idUsuarioTestigo | integer | Sí | Distinto del arqueador |
| desglose | Desglose[] | Sí |  |
| observaciones | string(500) | No |  |

```json
{
  "tipoArqueo": "Sorpresivo",
  "idUsuarioTestigo": 9,
  "desglose": [
    {
      "idDenominacion": 1,
      "cantidad": 9
    }
  ],
  "observaciones": null
}
```

## Response `201`

`ArqueoBoveda`

```json
{
  "idArqueoBoveda": 1,
  "idBoveda": 1,
  "fechaHoraArqueo": "2026-11-16T10:00:00-05:00",
  "tipoArqueo": "Sorpresivo",
  "idUsuarioArqueador": 7,
  "idUsuarioTestigo": 9,
  "estado": "REGISTRADO",
  "idMovimientoAjuste": null,
  "idsMovimientosAjuste": [],
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
  "idUsuarioAprobador": null,
  "fechaHoraAprobacion": null
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `ARQUEADOR_IGUAL_TESTIGO` | El arqueador y el testigo son la misma persona |

## Definición de terminado

- [x] Contrato implementado en OpenAPI generado (`/api/openapi.json`); no existe `openapi.yaml` en este repositorio
- [x] Pruebas del caso feliz y errores documentados

## Implementación BOV-01..06

Reglas adicionales, errores, migración y configuración contable: [documentación del módulo](../../../Backend/docs/BOV-01-06-bovedas.md). Los ejemplos anteriores usan datos ficticios coherentes; no son semillas de producción.
