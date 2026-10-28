---
number: 201
title: "CLI-13 | POST /api/v1/clientes/{idCliente}/evaluaciones-riesgo"
type: api
code: CLI-13
parent: "[[C-08 Registro de la evaluación de riesgo LAFT, PEP y anteced]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/201
---

`POST /api/v1/clientes/{idCliente}/evaluaciones-riesgo` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** C-08 (#58) · **OpenAPI:** `CLI13`

Registra evaluación de riesgo LAFT/PEP.

| Lee | Escribe | DB |
|---|---|---|
| `Catalogo.TipoAntecedente` | `Clientes.RiesgoCliente` | `Clientes.trg_RiesgoCliente_Evaluacion` |

## Reglas de negocio

1. `tieneAntecedentes = true` exige `idTipoAntecedente` (activo); `false` lo prohíbe (`CK_RiesgoCliente_Antecedente`) → `422 ANTECEDENTE_REQUERIDO`.
2. `Evaluador` sale del token; se inserta con `EsVigente = 0`.
3. El trigger marca vigente la última evaluación y cambia el cliente: `Rechazado` → `Bloqueado`; `Aprobado` desde `Pendiente` → `Activo`; `Observado` → sin cambio.
4. Un antecedente con `PuedeImpedirVinculacion = 1` impide abrir cuentas y créditos aunque el resultado sea Aprobado.

## Flujo

1. Validar cliente y antecedente.
2. Insertar la evaluación (el trigger actualiza vigencia y estado).
3. Responder 201 con la evaluación y el nuevo estado del cliente.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCliente | path | integer | Sí |  |

Body `RiesgoCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| nivelRiesgoLAFT | Bajo \| Medio \| Alto | Sí |  |
| esPEP | boolean | No |  |
| resultadoEvaluacion | Aprobado \| Observado \| Rechazado | Sí |  |
| tieneAntecedentes | boolean | No |  |
| idTipoAntecedente | integer | No | Obligatorio si tieneAntecedentes |
| observaciones | string(250) | No |  |

```json
{
  "nivelRiesgoLAFT": "Bajo",
  "esPEP": true,
  "resultadoEvaluacion": "Aprobado",
  "tieneAntecedentes": true,
  "idTipoAntecedente": 1,
  "observaciones": "observaciones"
}
```

## Response `201`

`Riesgo`

```json
{
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
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `ANTECEDENTE_REQUERIDO` | Hay antecedentes sin tipo, o tipo sin antecedentes |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
