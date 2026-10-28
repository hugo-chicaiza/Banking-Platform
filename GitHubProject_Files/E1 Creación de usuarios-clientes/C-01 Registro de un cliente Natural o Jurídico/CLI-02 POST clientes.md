---
number: 183
title: "CLI-02 | POST /api/v1/clientes"
type: api
code: CLI-02
parent: "[[C-01 Registro de un cliente Natural o Jurídico]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/183
---

`POST /api/v1/clientes` · **Roles:** ASESOR, ADMIN · **Historia:** C-01 (#39), también C-02 · **OpenAPI:** `CLI02`

Registra un cliente (Natural o Jurídico) con dirección principal.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.ActividadEconomica`, `Catalogo.Paises`, `Catalogo.Ciudad` | `Clientes.Cliente`, `Clientes.Direcciones`, `Clientes.ClientesHis` | — |

## Reglas de negocio

1. Identificación única (`UQ` en `Cliente`) → `409 CLIENTE_DUPLICADO`; formato por tipo como en CLI-01 → `422 DOCUMENTO_INVALIDO`.
2. Natural exige `apellidos`, `genero` y `estadoCivil`; Jurídico exige `razonSocial` y no admite esos tres (`CK_Cliente_TipoPersona`) → `422 TIPO_PERSONA_INVALIDO`.
3. `consentimientoDatos` debe ser `true` → `422 CONSENTIMIENTO_REQUERIDO`; `FechaConsentimiento` la fija el backend.
4. `fechaNacimiento` debe ser anterior a hoy.
5. El cliente se crea en `Pendiente`: pasa a `Activo` cuando su evaluación de riesgo queda `Aprobado` (CLI-13).
6. `CreadoPor` sale del token; la IP (`X-Forwarded-For`) va a `ClientesHis`.

## Flujo

1. Validar documento, tipo de persona, consentimiento y catálogos (actividad, país, ciudad).
2. Insertar `Cliente`, su dirección principal y la fila de `ClientesHis` (`TipoOperacion = 'I'`) en una transacción.
3. Responder 201 con el cliente.

## Request

Body `ClienteCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| identificacion | string(13) | Sí | Cédula(10)/RUC(13)/Pasaporte |
| tipoDocumento | C \| R \| P | Sí | Cédula, RUC, Pasaporte |
| tipoCliente | Natural \| Juridico | Sí |  |
| nombres | string | Sí |  |
| apellidos | string | No | Obligatorio si Natural; prohibido si Jurídico |
| razonSocial | string | No | Obligatorio si Jurídico |
| nombreComercial | string | No |  |
| idActividadEconomica | integer | No |  |
| fechaNacimiento | string | Sí | Fecha de nacimiento o de constitución; debe ser pasada |
| genero | M \| F | No | Obligatorio si Natural |
| estadoCivil | Soltero \| Casado \| Divorciado \| Viudo \| Union Libre | No | Obligatorio si Natural |
| codigoPaisNacionalidad | string(3) | No | Default ECU |
| telefonoConvencional | string(15) | No |  |
| telefonoCelular | string(15) | Sí |  |
| email | string(150) | Sí |  |
| consentimientoDatos | boolean | Sí | Debe ser true |
| direccion | DireccionCreate | Sí |  |

```json
{
  "identificacion": "1712345678",
  "tipoDocumento": "C",
  "tipoCliente": "Natural",
  "nombres": "María José",
  "apellidos": "López Pérez",
  "idActividadEconomica": 1,
  "fechaNacimiento": "1990-05-14",
  "genero": "M",
  "estadoCivil": "Soltero",
  "codigoPaisNacionalidad": "ECU",
  "telefonoConvencional": "022345678",
  "telefonoCelular": "0991234567",
  "email": "maria.lopez@correo.ec",
  "consentimientoDatos": true,
  "direccion": {
    "tipoDireccion": "Domicilio",
    "codigoPais": "ECU",
    "idCiudad": 1,
    "sector": "La Mariscal",
    "calleDireccion": "Av. Amazonas N24-123",
    "referenciaUbicacion": "Frente al parque",
    "codigoPostal": "170143",
    "esPrincipal": true
  }
}
```

## Response `201`

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
| 409 | `CLIENTE_DUPLICADO` | Ya existe un cliente con esa identificación |
| 422 | `DOCUMENTO_INVALIDO` | El documento no cumple el formato de su tipo |
| 422 | `TIPO_PERSONA_INVALIDO` | Faltan o sobran datos según Natural o Jurídico |
| 422 | `CONSENTIMIENTO_REQUERIDO` | No se aceptó el tratamiento de datos |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
