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
4. Una dirección eliminada no se edita (`409 DIRECCION_NO_EDITABLE`). Una dirección inactiva no se promueve a principal (`409 DIRECCION_NO_ACTIVA`).
5. La principal activa no admite `esPrincipal: false`: se debe promover otra (`409 DIRECCION_PRINCIPAL_REQUERIDA`).
6. Alta, edición y baja toman el bloqueo del cliente hasta commit/rollback. PATCH actualiza únicamente los campos enviados y modificados; los omitidos conservan el valor persistido.
7. Texto de calle/referencia: 1–250 caracteres, no solo espacios; sector: máximo 50; código postal: seis dígitos ASCII. null solo borra sector y código postal. Se rechazan campos desconocidos.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |
| idDireccion | path | integer | Sí |  |

Body `DireccionUpdate` (todos los campos son opcionales):

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoDireccion | Domicilio \| Trabajo \| Correspondencia \| Otra | No | No admite null |
| codigoPais | string(3) | No | Se valida contra la ciudad final; no admite null |
| idCiudad | integer | No | No admite null |
| sector | string(50) | No | Admite null |
| calleDireccion | string(250) | No | No admite null ni solo espacios |
| referenciaUbicacion | string(250) | No | No admite null ni solo espacios |
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

Formato ProblemDetails (ver F-04). 400 para datos inválidos; 401/403 para sesión/permisos; 404 para cliente o dirección inexistente; 409 para cliente eliminado o los conflictos de principal descritos arriba; 422 para catálogo inválido.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
