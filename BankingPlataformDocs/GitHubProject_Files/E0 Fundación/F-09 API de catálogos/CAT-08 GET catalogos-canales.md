---
number: 121
title: "CAT-08 | GET /api/v1/catalogos/canales"
type: api
code: CAT-08
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/121
---

`GET /api/v1/catalogos/canales` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT08`

Lista los canales de operación (ventanilla, ATM, digital) y qué exige cada uno.

| Lee | Escribe | DB |
|---|---|---|
| `Canal.Canal` | — | — |

## Reglas de negocio

1. Solo `Estado = 'A'`, ordenados por `nombreCanal`.
2. `requiereTarjeta`, `requierePin`, `requiereTerminal`, `requiereJornadaCaja` los usa el backend de cada módulo para validar; el FE solo los muestra.
3. `modo` = `ModoDigitalPresencial` (`Digital` \| `Presencial` \| `Ambos`).

## Request

Sin parámetros.

## Response `200`

```json
[ { "idCanal": 2, "codigoCanal": "ATM", "nombreCanal": "Cajero automático", "requiereTarjeta": true, "requierePin": true, "requiereTerminal": true, "requiereJornadaCaja": false, "modo": "Presencial" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, excluye inactivos, sin token
