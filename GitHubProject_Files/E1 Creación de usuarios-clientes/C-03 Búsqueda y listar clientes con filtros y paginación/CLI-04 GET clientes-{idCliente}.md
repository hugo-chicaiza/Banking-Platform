---
number: 185
title: "CLI-04 | GET /api/v1/clientes/{idCliente}"
type: api
code: CLI-04
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/185
---

`GET /api/v1/clientes/{idCliente}` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** C-03 (#45) · **OpenAPI:** `CLI04`

Detalle del cliente.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Cliente`, `Clientes.Direcciones` | — | — |

## Reglas de negocio

1. Cliente inexistente → 404.
2. Incluye solo las direcciones con `Estado = 'Activo'`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

## Response `200`

`Cliente`

```json
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
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
