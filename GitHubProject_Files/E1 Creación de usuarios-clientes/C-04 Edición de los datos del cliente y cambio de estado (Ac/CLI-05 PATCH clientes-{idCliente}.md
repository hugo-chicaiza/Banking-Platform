---
number: 186
title: "CLI-05 | PATCH /api/v1/clientes/{idCliente}"
type: api
code: CLI-05
parent: "[[C-04 Edición de los datos del cliente y cambio de estado (Ac]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/186
---

`PATCH /api/v1/clientes/{idCliente}` · **Roles:** ASESOR, ADMIN · **Historia:** C-04 (#47) · **OpenAPI:** `CLI05`

Edita datos del cliente (registra auditoría por campo).

| Lee | Escribe | DB |
|---|---|---|
| — | `Clientes.Cliente`, `Clientes.ClientesHis` | — |

## Reglas de negocio

1. `identificacion`, `tipoDocumento` y `tipoCliente` no se editan.
2. Cliente `Eliminado` → `409 CLIENTE_NO_EDITABLE`.
3. Se mantiene `CK_Cliente_TipoPersona` (Natural / Jurídico) → 422 si se rompe.
4. Una fila de `ClientesHis` (`TipoOperacion = 'U'`) por cada campo modificado, con valor anterior, nuevo, usuario e IP.

## Flujo

1. Cargar el cliente y comparar campo por campo.
2. Actualizar `Cliente` e insertar las filas de `ClientesHis` en una transacción.
3. Responder 200 con el cliente.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

Body `ClienteUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| nombres | string | No |  |
| apellidos | string | No |  |
| razonSocial | string | No |  |
| nombreComercial | string | No |  |
| idActividadEconomica | integer | No |  |
| estadoCivil | string | No |  |
| telefonoConvencional | string | No |  |
| telefonoCelular | string | No |  |
| email | string | No |  |

```json
{
  "nombres": "María José",
  "apellidos": "López Pérez",
  "razonSocial": "Comercial Andes S.A.",
  "nombreComercial": "Andes",
  "idActividadEconomica": 1,
  "estadoCivil": "Soltero",
  "telefonoConvencional": "022345678",
  "telefonoCelular": "0991234567",
  "email": "maria.lopez@correo.ec"
}
```

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

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CLIENTE_NO_EDITABLE` | El cliente está Eliminado |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
