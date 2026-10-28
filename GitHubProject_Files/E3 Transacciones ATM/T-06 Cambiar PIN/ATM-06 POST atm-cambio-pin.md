---
number: 146
title: "ATM-06 | POST /api/v1/atm/cambio-pin"
type: api
code: ATM-06
parent: "[[T-06 Cambiar PIN]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/146
---

`POST /api/v1/atm/cambio-pin` · **Roles:** ATM (sesión) · **Historia:** T-06 (#11) · **OpenAPI:** `ATM06`

Cambio de PIN.

| Lee | Escribe | DB |
|---|---|---|
| — | `Tarjeta.TarjetaHis`, `SeguridadDB.TarjetaPIN` | — |

## Reglas de negocio

1. Exige el PIN actual → `401 PIN_INCORRECTO` (suma intento, como ATM-01).
2. PIN nuevo de 4 dígitos, distinto del actual y no trivial → `422 PIN_DEBIL`.
3. Se guarda solo hash + salt; registra `TarjetaHis` (`CambioPin`) sin el PIN.

## Flujo

1. Verificar el PIN actual.
2. Validar y guardar el nuevo hash junto con el historial en una transacción.
3. Responder 204.

## Request

Body `AtmCambioPinRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| pinActual | string(4) | Sí |  |
| pinNuevo | string(4) | Sí |  |

```json
{
  "pinActual": "pinActual",
  "pinNuevo": "pinNuevo"
}
```

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `PIN_INCORRECTO` | El PIN no coincide |
| 422 | `PIN_DEBIL` | PIN trivial o igual al anterior |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- Depende de G-02 (hash y salt en `TarjetaPIN`).
