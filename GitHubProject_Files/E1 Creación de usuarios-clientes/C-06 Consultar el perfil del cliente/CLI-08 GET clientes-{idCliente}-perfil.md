---
number: 196
title: "CLI-08 | GET /api/v1/clientes/{idCliente}/perfil"
type: api
code: CLI-08
parent: "[[C-06 Consultar el perfil del cliente]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/196
---

`GET /api/v1/clientes/{idCliente}/perfil` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** C-06 (#49) · **OpenAPI:** `CLI08`

Perfil: riesgo, cuentas, tarjetas y créditos.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.*`, `Cuentas.Cuenta`, `Tarjeta.Tarjeta`, `Credito.CreditoSolicitud/CreditoResumen` | — | — |

## Reglas de negocio

1. Solo lectura: devuelve riesgo vigente, cuentas, tarjetas (solo máscara, nunca PAN) y créditos.
2. Colecciones vacías si el cliente no tiene productos; cliente inexistente → 404.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

## Response `200`

`ClientePerfil`

```json
{
  "cliente": {
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
  },
  "riesgoVigente": {
    "idEvaluacion": 1,
    "idCliente": 1,
    "nivelRiesgoLAFT": "nivelRiesgoLAFT",
    "esPEP": true,
    "resultadoEvaluacion": "resultadoEvaluacion",
    "fechaEvaluacion": "2026-11-04T10:15:00-05:00",
    "evaluador": 12,
    "tieneAntecedentes": true,
    "idTipoAntecedente": 1,
    "observaciones": "observaciones"
  },
  "cuentas": [
    {
      "idCuenta": 1,
      "numeroCuenta": "100200300401",
      "idCliente": 1,
      "idAgencia": "001",
      "idProducto": 1,
      "tipoCuenta": "Ahorro",
      "idMoneda": 1,
      "saldo": 150.0,
      "saldoRetenido": 150.0,
      "saldoDisponible": 150.0,
      "estado": "Activa",
      "fechaApertura": "2026-11-04T10:15:00-05:00",
      "fechaUltimoMovimiento": "2026-11-04T10:15:00-05:00",
      "fechaCierre": "2026-11-04T10:15:00-05:00"
    }
  ],
  "tarjetas": [
    {
      "idTarjeta": 1,
      "tokenTarjeta": "TOKEN_FICTICIO",
      "numeroEnmascarado": "numeroEnmascarado",
      "tipoTarjeta": "tipoTarjeta",
      "nombreTarjeta": "nombreTarjeta",
      "idCliente": 1,
      "idCuenta": 1,
      "idProducto": 1,
      "estadoActual": "estadoActual",
      "pinAsignado": true,
      "fechaEmision": "2026-11-04",
      "fechaExpiracion": "2026-11-04"
    }
  ],
  "creditos": [
    {
      "idSolicitud": 1,
      "numeroSolicitud": "numeroSolicitud",
      "tipoCredito": "tipoCredito",
      "montoDesembolsado": 150.0,
      "saldoCapital": 150.0,
      "proximaCuota": "2026-11-04",
      "estado": "EN_TRAMITE"
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
