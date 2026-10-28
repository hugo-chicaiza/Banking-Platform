---
number: 115
title: "CAT-02 | GET /api/v1/catalogos/paises/{codigoPais}/ciudades"
type: api
code: CAT-02
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/115
---

`GET /api/v1/catalogos/paises/{codigoPais}/ciudades` · **Roles:** AUTH · **Historia:** F-09 (#109) · **OpenAPI:** `CAT02`

Lista las ciudades de un país, con búsqueda opcional por nombre.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.Ciudad`, `Catalogo.Paises` | — | — |

## Reglas de negocio

1. Solo ciudades del país, ordenadas por `provincia` y `nombre`.
2. `q` filtra por coincidencia parcial, sin distinguir mayúsculas ni tildes.
3. País inexistente → `404 PAIS_NO_ENCONTRADO`; país sin ciudades o sin coincidencias → `200 []`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| codigoPais | path | str(3) | Sí | ISO 3166-1 alfa-3 |
| q | query | str | No | Búsqueda por nombre |

## Response `200`

```json
[ { "idCiudad": 1, "codigoPais": "ECU", "nombre": "Quito", "provincia": "Pichincha" } ]
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `PAIS_NO_ENCONTRADO` | `codigoPais` no existe |

## Definición de terminado

- [ ] Coincide con `openapi.yaml`
- [ ] Prueba: con `q`, sin `q`, país inexistente, sin token
