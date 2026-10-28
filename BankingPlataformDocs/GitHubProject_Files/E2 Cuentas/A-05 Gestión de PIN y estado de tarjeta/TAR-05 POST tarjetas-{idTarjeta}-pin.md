---
number: 133
title: "TAR-05 | POST /api/v1/tarjetas/{idTarjeta}/pin"
type: api
code: TAR-05
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/133
---

`POST /api/v1/tarjetas/{idTarjeta}/pin` · **Roles:** ASESOR, ADMIN · **Historia:** A-05 (#59) · **OpenAPI:** `TAR05`

Asigna el PIN inicial.

| Lee | Escribe | DB |
|---|---|---|
| — | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis` | — |

## Reglas de negocio

1. Solo si `PinAsignado = 0` → si no, `409 PIN_YA_ASIGNADO`.
2. PIN de 4 dígitos; se rechazan secuencias y repetidos (1234, 0000) → `422 PIN_DEBIL`.
3. El PIN viaja solo por TLS, se guarda con hash + salt y nunca aparece en logs, respuestas ni errores.
4. Marca `PinAsignado = 1` y registra `TarjetaHis` (`CambioPin`) sin el PIN.

## Flujo

1. Validar estado del PIN y fortaleza.
2. Guardar hash + salt, marcar `PinAsignado` e insertar historial en una transacción.
3. Responder 204.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |

Body `PinAsignar`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| pin | string(4) | Sí | 4 dígitos; solo viaja por TLS, se guarda con hash+salt |

```json
{
  "pin": "pin"
}
```

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `PIN_YA_ASIGNADO` | La tarjeta ya tiene PIN |
| 422 | `PIN_DEBIL` | PIN trivial o igual al anterior |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- Dónde se guarda el hash: `SeguridadDB.TarjetaPIN` existe pero no tiene columnas de hash ni salt (brecha G-02, aplicar en F-08).
