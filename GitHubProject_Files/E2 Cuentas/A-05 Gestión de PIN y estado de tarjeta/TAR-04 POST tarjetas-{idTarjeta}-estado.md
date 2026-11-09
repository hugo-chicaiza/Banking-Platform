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

Cambia el estado de la tarjeta (aprobar, rechazar, generar, bloquear, cancelar…). Al aprobar, genera el PIN automáticamente.

| Lee | Escribe | DB / Componente |
|---|---|---|
| `Tarjeta.Tarjeta`, `Tarjeta.TransicionEstado`, repositorio aislado de PAN ficticios | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis`, `SeguridadDB.Tarjetas.TarjetaPIN` | `Tarjeta.trg_Tarjeta_Reglas` (DB 52005), HSM |

## Estados

`Solicitada`, `Aprobada`, `Generada`, `Activa`, `Inactiva`, `Bloqueada`, `Cancelada`, `Anulada`, `Vencida`, `Cerrada` (`CK_Tarjeta_Estado`). Terminales: `Cancelada`, `Anulada`, `Vencida`, `Cerrada`.

| Origen | Destinos permitidos (`Tarjeta.TransicionEstado`) |
|---|---|
| Solicitada | Aprobada, Anulada (rechazo) |
| Aprobada | Generada, Anulada |
| Generada | Activa (solo automática, ver regla 4), Anulada |
| Activa | Bloqueada, Inactiva, Cancelada, Vencida, Cerrada |
| Bloqueada | Activa, Cancelada |
| Inactiva | Activa, Cancelada, Cerrada |
| Vencida | Cerrada |

## Reglas de negocio

1. Solo transiciones de `Tarjeta.TransicionEstado` → si no, `409 TRANSICION_INVALIDA` (también DB 52005).
2. **Aprobar** (`Solicitada → Aprobada`): registra `FechaResolucion` y genera el PIN automáticamente en el HSM. Nadie (asesor, supervisor ni administrador) conoce ni envía el PIN:
   - El HSM genera un PIN aleatorio de 4 dígitos no trivial y su IBM 3624 PIN Offset, con los mismos parámetros que ATM-01. El PIN no sale del HSM; solo se guarda el Offset en `SeguridadDB.Tarjetas.TarjetaPIN`.
   - **Débito:** el PIN es temporal (`RequiereCambio = 1`). Llega impreso en la hoja que acompaña a la tarjeta; el canal de entrega no se simula.
   - **Crédito:** el PIN se asigna pero no se entrega (`RequiereCambio = 0`). Si el cliente lo necesita, lo pide al servicio al cliente (no se simula).
   - Se marca `PinAsignado = 1` y se registran en `TarjetaHis` el cambio de estado y un evento `CambioPin` (“PIN generado automáticamente”), sin datos sensibles.
3. **Rechazar** (`Solicitada → Anulada`): registra `FechaResolucion`.
4. **Generar** (`Aprobada → Generada`): la tarjeta física queda emitida; `FechaEmision` pasa a la fecha actual y `FechaExpiracion` a cinco años después.
5. `Generada → Activa` **no se hace con esta API** → `409 ACTIVACION_AUTOMATICA`. La activación es automática:
   - **Débito:** con el primer cambio de PIN en el ATM (ATM-01 abre una sesión restringida y ATM-06 activa la tarjeta).
   - **Crédito:** a los 3 días laborables desde `FechaEmision`, según `Contabilidad.FechaContable.EsDiaContable` (ATM-01 la activa al usarla; ver Pendiente).
6. Volver a `Activa` desde `Bloqueada` o `Inactiva` exige PIN asignado (`PinAsignado = 1`) → si no, `409 PIN_NO_ASIGNADO`.
7. `motivo` obligatorio; `TarjetaHis` guarda estado anterior, nuevo, usuario, canal e IP. Es texto legible que se muestra en TAR-06: el OpenAPI trae un ejemplo real (`Solicitud del cliente aprobada`) para que Swagger no proponga texto aleatorio generado desde el patrón.
8. Bloquear la tarjeta no bloquea la cuenta.
9. El PIN, el PAN y el PIN Offset nunca aparecen en respuestas, logs ni errores.

## Flujo

1. Bloquear la fila de la tarjeta y validar la transición contra `TransicionEstado` y las reglas 5 y 6.
2. Si el destino es `Aprobada`: obtener el PAN ficticio, pedir al HSM el PIN y su Offset, y guardar el Offset en `SeguridadDB` (confirmado antes de seguir). Si CooperativaDB falla después, la tarjeta sigue en `Solicitada` y no se puede usar; repetir la aprobación genera un PIN nuevo que reemplaza al anterior.
3. En una transacción de CooperativaDB: actualizar `Estado` (y `PinAsignado`, `FechaResolucion` o `FechaEmision`/`FechaExpiracion` según el destino) e insertar `TarjetaHis`.
4. Responder 200.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |

Body `TarjetaEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | Aprobada \| Generada \| Activa \| Inactiva \| Bloqueada \| Cancelada \| Anulada \| Vencida \| Cerrada | Sí | `Solicitada` solo es el estado inicial (TAR-01) |
| motivo | string(500) | Sí |  |

```json
{
  "estado": "Aprobada",
  "motivo": "Solicitud del cliente aprobada"
}
```

## Response `200`

`Tarjeta`

```json
{
  "idTarjeta": 301,
  "tokenTarjeta": "TOKEN_FICTICIO",
  "numeroEnmascarado": "4540 12** **** 3456",
  "tipoTarjeta": "Debito",
  "nombreTarjeta": "MARIA MENDOZA",
  "idCliente": 125,
  "idCuenta": 501,
  "idProducto": 4,
  "estadoActual": "Aprobada",
  "pinAsignado": true,
  "fechaSolicitud": "2026-11-04",
  "fechaResolucion": "2026-11-05T10:15:00",
  "fechaEmision": "2026-11-04",
  "fechaExpiracion": "2031-11-04"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `TARJETA_NO_ENCONTRADA` | La tarjeta de la URL no existe |
| 409 | `TRANSICION_INVALIDA` | El cambio de estado no está permitido (también DB 52005) |
| 409 | `ACTIVACION_AUTOMATICA` | Se intenta pasar de `Generada` a `Activa` a mano |
| 409 | `PIN_NO_ASIGNADO` | Se intenta reactivar una tarjeta sin PIN |
| 503 | `HSM_NO_DISPONIBLE` | No se pudo generar el PIN al aprobar |
| 503 | `PAN_NO_DISPONIBLE` | No se pudo obtener el PAN ficticio para generar el PIN |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Prueba de aprobación: PIN generado, `RequiereCambio` según el tipo de tarjeta y `FechaResolucion` registrada
- [ ] Sin PAN, PIN, PIN Offset, contraseñas ni tokens en logs

## Pendiente

- [ ] Proceso programado que active las tarjetas de crédito al cumplir 3 días laborables, para que TAR-02 y TAR-03 lo reflejen aunque la tarjeta no se haya usado en un ATM.
- [ ] Canal de entrega del PIN de débito (hoja impresa con la tarjeta) y solicitud del PIN de crédito por servicio al cliente: no se simulan.
