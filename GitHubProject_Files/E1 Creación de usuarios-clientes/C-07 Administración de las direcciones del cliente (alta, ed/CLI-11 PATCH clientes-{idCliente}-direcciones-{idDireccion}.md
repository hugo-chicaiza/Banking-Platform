---
number: 199
title: "CLI-11 | PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}"
type: api
code: CLI-11
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/199
---

`PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}` · **Roles:** ASESOR, ADMIN · **Historia:** C-07 (#57) · **OpenAPI:** `CLI11`

Edita una dirección o la marca principal.

| Lee | Escribe | DB |
|---|---|---|
| — | `Clientes.Direcciones`, `Clientes.ClientesHis` | — |

## Reglas de negocio

1. Marcar como principal desmarca la anterior en la misma transacción.
2. Cada campo cambiado va a `ClientesHis`.
3. Dirección de otro cliente o inexistente → 404.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |
| idDireccion | path | integer | Sí |  |

Body `DireccionCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoDireccion | Domicilio \| Trabajo \| Correspondencia \| Otra | Sí |  |
| codigoPais | string(3) | No | Default ECU |
| idCiudad | integer | Sí |  |
| sector | string | No |  |
| calleDireccion | string | Sí |  |
| referenciaUbicacion | string | Sí |  |
| codigoPostal | string(6) | No | 6 dígitos |
| esPrincipal | boolean | No |  |

```json
{
  "tipoDireccion": "Domicilio",
  "codigoPais": "ECU",
  "idCiudad": 1,
  "sector": "La Mariscal",
  "calleDireccion": "Av. Amazonas N24-123",
  "referenciaUbicacion": "Frente al parque",
  "codigoPostal": "170143",
  "esPrincipal": true
}
```

## Response `200`

`Direccion`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
