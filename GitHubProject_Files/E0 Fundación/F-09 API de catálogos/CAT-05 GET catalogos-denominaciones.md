---
number: 118
title: "CAT-05 | GET /api/v1/catalogos/denominaciones"
type: api
code: CAT-05
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/118
---

`GET /api/v1/catalogos/denominaciones` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT05`

Lista las denominaciones de billetes y monedas para caja, bóveda y ATM.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.Denominacion` (`Estado = 'A'`) | — | — |

## Reglas de negocio

1. Orden de conteo: billetes primero, luego por `valor` descendente.
2. `valor` > 0 y decimal (nunca float); único por (`tipoPieza`, `valor`).

## Request

Sin parámetros.

## Response `200`

```json
[
  { "idDenominacion": 1, "tipoPieza": "Billete", "valor": 20.00, "descripcion": "Billete de 20" },
  { "idDenominacion": 8, "tipoPieza": "Moneda", "valor": 0.25, "descripcion": "Moneda de 25 ctvs" }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: orden correcto, sin token
