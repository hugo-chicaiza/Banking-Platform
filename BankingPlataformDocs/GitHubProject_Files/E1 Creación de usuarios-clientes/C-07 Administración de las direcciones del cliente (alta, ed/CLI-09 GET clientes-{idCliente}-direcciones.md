---
number: 197
title: "CLI-09 | GET /api/v1/clientes/{idCliente}/direcciones"
type: api
code: CLI-09
parent: "[[C-07 Administración de las direcciones del cliente (alta, ed]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/197
---

`GET /api/v1/clientes/{idCliente}/direcciones` · **Roles:** ASESOR, ADMIN · **Historia:** C-07 (#57) · **OpenAPI:** `CLI09`

Direcciones del cliente.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Direcciones` | — | — |

## Reglas de negocio

1. Devuelve direcciones `Activo` e `Inactivo`; la principal primero.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idDireccion": 1,
    "tipoDireccion": "Domicilio",
    "codigoPais": "ECU",
    "idCiudad": 1,
    "sector": "La Mariscal",
    "calleDireccion": "Av. Amazonas N24-123",
    "referenciaUbicacion": "Frente al parque",
    "codigoPostal": "170143",
    "esPrincipal": true,
    "estado": "Activo"
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
