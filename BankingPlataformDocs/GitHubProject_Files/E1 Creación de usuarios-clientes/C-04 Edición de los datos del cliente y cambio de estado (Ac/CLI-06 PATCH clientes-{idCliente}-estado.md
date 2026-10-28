---
number: 187
title: "CLI-06 | PATCH /api/v1/clientes/{idCliente}/estado"
type: api
code: CLI-06
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/187
---

`PATCH /api/v1/clientes/{idCliente}/estado` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** C-04 (#47) · **OpenAPI:** `CLI06`

Cambia el estado del cliente.

| Lee | Escribe | DB |
|---|---|---|
| — | `Clientes.Cliente`, `Clientes.ClientesHis` | — |

## Reglas de negocio

1. Transiciones permitidas: Activo ⇄ Inactivo; Activo → Suspendido → Activo; Activo → Bloqueado → Activo (solo SUPERVISOR); cualquiera → Eliminado (baja lógica). Otra → 409.
2. No pasa a `Inactivo` ni `Eliminado` con cuentas con saldo o créditos vigentes → `409 CLIENTE_CON_PRODUCTOS_VIGENTES`.
3. `motivo` obligatorio; se registra en `ClientesHis`.

## Flujo

1. Validar la transición y los productos vigentes.
2. Actualizar `Estado` e insertar `ClientesHis` en una transacción.
3. Responder 200.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

Body `ClienteEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | Activo \| Inactivo \| Suspendido \| Bloqueado \| Eliminado | Sí |  |
| motivo | string | Sí | Se guarda en ClientesHis.Observaciones |

```json
{
  "estado": "Activo",
  "motivo": "Solicitud del cliente"
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
| 409 | `CLIENTE_CON_PRODUCTOS_VIGENTES` | Tiene cuentas con saldo o créditos vigentes |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- Confirmar con negocio la regla de productos vigentes (propuesta del contrato).
