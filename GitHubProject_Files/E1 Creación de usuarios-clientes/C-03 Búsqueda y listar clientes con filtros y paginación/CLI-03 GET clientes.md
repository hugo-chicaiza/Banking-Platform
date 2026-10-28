---
number: 184
title: "CLI-03 | GET /api/v1/clientes"
type: api
code: CLI-03
parent: "[[C-03 Búsqueda y listar clientes con filtros y paginación]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/184
---

`GET /api/v1/clientes` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** C-03 (#45) · **OpenAPI:** `CLI03`

Busca y lista clientes.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Cliente` | — | — |

## Reglas de negocio

1. `q` busca por nombres, apellidos, razón social o identificación (parcial); `identificacion` es exacta.
2. Paginado `{ items, page, pageSize, total }`; `pageSize` máx. 100; `sort` solo por campos permitidos.
3. Sin resultados → `200` con `items: []`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| q | query | string | No | Nombre/razón social/identificación |
| identificacion | query | string | No | Exacta |
| tipoCliente | query | string | No | Natural/Juridico |
| estado | query | string | No | Estado |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageCliente`

```json
{
  "items": [
    {
      "idCliente": 1,
      "identificacion": "1712345678",
      "tipoDocumento": "C",
      "tipoCliente": "Natural",
      "nombres": "María José",
      "apellidos": "López Pérez",
      "idActividadEconomica": 1,
      "fechaNacimiento": "1990-05-14",
      "genero": "F",
      "estadoCivil": "Soltero",
      "codigoPaisNacionalidad": "ECU",
      "telefonoConvencional": "022345678",
      "telefonoCelular": "0991234567",
      "email": "maria.lopez@correo.ec",
      "consentimientoDatos": true,
      "fechaConsentimiento": "2026-11-04T10:15:00-05:00",
      "estado": "Activo",
      "fechaRegistro": "2026-11-04T10:15:00-05:00",
      "creadoPor": 12,
      "direcciones": [
        {
          "idDireccion": null,
          "tipoDireccion": null,
          "codigoPais": null,
          "idCiudad": null,
          "sector": null,
          "calleDireccion": null,
          "referenciaUbicacion": null,
          "codigoPostal": null,
          "esPrincipal": null,
          "estado": null
        }
      ]
    }
  ],
  "page": 12,
  "pageSize": 12,
  "total": 12
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
