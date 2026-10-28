---
number: 117
title: "CAT-04 | GET /api/v1/catalogos/tipos-antecedente"
type: api
code: CAT-04
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/117
---

`GET /api/v1/catalogos/tipos-antecedente` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT04`

Lista los tipos de antecedente de la evaluación de riesgo del cliente (C-08).

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.TipoAntecedente` (`Estado = 'Activo'`) | — | — |

## Reglas de negocio

1. `categoria` es `EnRevision` o `Critico`; ordenados por `categoria` y `nombre`.
2. `puedeImpedirVinculacion` solo informa; la regla que bloquea vive en C-08.

## Request

Sin parámetros.

## Response `200`

```json
[ { "idTipoAntecedente": 2, "nombre": "Lista OFAC", "categoria": "Critico", "puedeImpedirVinculacion": true } ]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con datos, sin token
