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

1. Transiciones permitidas: Activo ⇄ Inactivo; Activo → Suspendido → Activo; Activo → Bloqueado → Activo; cualquier estado no eliminado → Eliminado. Bloqueo/desbloqueo admiten ASESOR, SUPERVISOR y ADMIN, según aclaración del 2026-11-04. Otra transición, incluido solicitar el mismo estado, produce `409 TRANSICION_CLIENTE_INVALIDA`. Eliminado no se reactiva.
2. No pasa a `Inactivo` ni `Eliminado` con cuentas Activa/Bloqueada, o con Saldo > 0 o SaldoRetenido > 0 en cualquier estado, ni con un crédito desembolsado que conserve deuda → `409 CLIENTE_CON_PRODUCTOS_VIGENTES`. Una solicitud por sí sola no prueba deuda. Se consultan cuotas del plan vigente, abonos, pagos y mora; crédito pagado y comprobado no bloquea. Información incompleta o contradictoria: `503 DEUDA_CLIENTE_NO_VERIFICABLE`, sin cambio de estado.
3. `motivo` obligatorio y no compuesto solo de espacios, máximo 500 caracteres. Se registra junto con anterior/nuevo en JSON versionado en `ClientesHis.Observaciones`. El JSON completo debe caber en VARCHAR(500), sin truncar; esto puede reducir el motivo disponible.
4. Identidad autenticada y metadato `idUsuario` del usuario en WorkOS. Cliente, lecturas de productos, actualización y auditoría comparten transacción; las consultas de validación usan UPDLOCK/HOLDLOCK hasta commit/rollback.

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
| 403 | `USUARIO_SIN_VINCULO_AUDITORIA` | El usuario WorkOS no tiene un ID entero vinculado en el servidor |
| 404 | `CLIENTE_NO_ENCONTRADO` | El cliente no existe |
| 409 | `TRANSICION_CLIENTE_INVALIDA` | Transición no permitida o mismo estado |
| 409 | `CLIENTE_CON_PRODUCTOS_VIGENTES` | Tiene cuentas con saldo o créditos vigentes |
| 422 | `AUDITORIA_EXCEDE_LIMITE` | El cambio y motivo completos no caben en Observaciones |
| 503 | `DEUDA_CLIENTE_NO_VERIFICABLE` | No se pudo comprobar el saldo vigente del crédito con plan, cuotas y pagos |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Regla confirmada

- Regla de productos y roles confirmada por el solicitante el 2026-11-04. No se modificó la base de datos.
