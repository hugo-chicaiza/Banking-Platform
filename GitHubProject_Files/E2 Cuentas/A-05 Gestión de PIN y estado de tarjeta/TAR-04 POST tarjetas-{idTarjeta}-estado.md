---
number: 132
title: "TAR-04 | POST /api/v1/tarjetas/{idTarjeta}/estado"
type: api
code: TAR-04
parent: "[[A-05 Gestión de PIN y estado de tarjeta]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/132
---

`POST /api/v1/tarjetas/{idTarjeta}/estado` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-05 (#59) · **OpenAPI:** `TAR04`

Cambia el estado (activar, bloquear, cancelar…).

| Lee | Escribe | DB |
|---|---|---|
| — | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis` | `Tarjeta.trg_Tarjeta_Reglas` |

## Reglas de negocio

1. Solo transiciones de `Tarjeta.TransicionEstado` → si no, `409 TRANSICION_INVALIDA` (DB 52005).
2. Activar exige PIN asignado (`PinAsignado = 1`).
3. Estados terminales: Cancelada, Anulada, Vencida, Cerrada.
4. `motivo` obligatorio; `TarjetaHis` guarda estado anterior, nuevo, usuario, canal e IP.
5. Bloquear la tarjeta no bloquea la cuenta.

## Flujo

1. Validar la transición contra `TransicionEstado`.
2. Actualizar `Estado` e insertar `TarjetaHis` en una transacción.
3. Responder 200.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |

Body `TarjetaEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | Aprobada \| Generada \| Activa \| Inactiva \| Bloqueada \| Cancelada \| Anulada | Sí |  |
| motivo | string | Sí |  |

```json
{
  "estado": "Aprobada",
  "motivo": "Solicitud del cliente"
}
```

## Response `200`

`Tarjeta`

```json
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
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `TRANSICION_INVALIDA` | El cambio de estado no está permitido |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
