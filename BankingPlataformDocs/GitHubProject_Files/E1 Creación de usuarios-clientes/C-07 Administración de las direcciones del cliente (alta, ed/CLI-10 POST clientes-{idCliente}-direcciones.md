---
number: 198
title: "CLI-10 | POST /api/v1/clientes/{idCliente}/direcciones"
type: api
code: CLI-10
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/198
---

`POST /api/v1/clientes/{idCliente}/direcciones` · **Roles:** ASESOR, ADMIN · **Historia:** C-07 (#57) · **OpenAPI:** `CLI10`

Agrega una dirección.

| Lee | Escribe | DB |
|---|---|---|
| — | `Clientes.Direcciones`, `Clientes.ClientesHis` | — |

## Reglas de negocio

1. Solo una dirección principal activa por cliente (`UX_Direcciones_Principal`): si `esPrincipal = true`, la anterior pasa a no principal en la misma transacción.
2. `codigoPostal` de 6 dígitos si se envía; `idCiudad` debe existir.
3. Cliente `Eliminado` → 409.

## Flujo

1. Validar cliente y ciudad.
2. Desmarcar la principal anterior si corresponde, insertar la dirección y su fila de `ClientesHis` en una transacción.
3. Responder 201.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

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

## Response `201`

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

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `DIRECCION_PRINCIPAL_EXISTENTE` | Choque con otra principal activa al guardar en paralelo |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
