---
number: 150
title: "ATM-12 | PATCH /api/v1/atm/terminales/{idATM}/estado"
type: api
code: ATM-12
parent: "[[T-12 Administrar terminales ATM]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/150
---

`PATCH /api/v1/atm/terminales/{idATM}/estado` · **Roles:** SUPERVISOR, ADMIN · **Historia:** T-12 (#105) · **OpenAPI:** `ATM12`

Cambia estado (activo/inactivo/mantenimiento).

| Lee | Escribe | DB |
|---|---|---|
| — | `ATM.ATM` | — |

## Reglas de negocio

1. Estados: activo, inactivo y mantenimiento. Un terminal no activo rechaza sesiones (ATM-01).
2. Pasar a mantenimiento actualiza `FechaUltimoMantenimiento`; `motivo` obligatorio.

## Flujo

1. SUPERVISOR o ADMIN selecciona terminal y nuevo estado.
2. Backend verifica permisos y transición permitida.
3. Actualiza el estado y devuelve el terminal.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idATM | path | integer | Sí |  |

Body `ATMTerminalEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | A \| I \| M | Sí |  |
| motivo | string | No |  |

```json
{
  "estado": "A",
  "motivo": "Solicitud del cliente"
}
```

## Response `200`

`ATMTerminal`

```json
{
  "idATM": 1,
  "codigoATM": "ATM00001",
  "tipoTerminal": "ATM",
  "idCanal": 2,
  "idAgencia": "001",
  "ubicacion": "Agencia de ejemplo",
  "estado": "M",
  "fechaInstalacion": "2026-11-10"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- El export de `ATM.ATM` no trae el CHECK de `Estado`: confirmar los valores con el DBA.
