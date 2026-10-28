---
number: 149
title: "ATM-11 | POST /api/v1/atm/terminales"
type: api
code: ATM-11
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/149
---

`POST /api/v1/atm/terminales` · **Roles:** ADMIN · **Historia:** T-12 (#105) · **OpenAPI:** `ATM11`

Da de alta un terminal.

| Lee | Escribe | DB |
|---|---|---|
| — | `ATM.ATM` | — |

## Reglas de negocio

1. `CodigoATM` (8 caracteres) único → `409 CODIGO_ATM_DUPLICADO`.
2. El canal debe exigir terminal (`RequiereTerminal = 1`) y la agencia estar activa.
3. Nace activo; las gavetas se configuran aparte.

## Flujo

1. ADMIN envía los datos del terminal.
2. Backend valida campos, referencias y unicidad del código.
3. Crea el terminal y devuelve su representación con HTTP 201.

## Request

Body `ATMTerminalCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| codigoATM | string(8) | Sí |  |
| codigoAdquirente | string(11) | Sí |  |
| tipoTerminal | ATM \| Kiosco \| POS | Sí |  |
| idCanal | integer | Sí |  |
| idAgencia | string(3) | No |  |
| ubicacion | string | No |  |
| numeroSerieATM | string | No |  |
| fechaInstalacion | string | Sí |  |

```json
{
  "codigoATM": "ATM00001",
  "codigoAdquirente": "COD01",
  "tipoTerminal": "ATM",
  "idCanal": 1,
  "idAgencia": "001",
  "ubicacion": "ubicacion",
  "numeroSerieATM": "numeroSerieATM",
  "fechaInstalacion": "2026-11-04"
}
```

## Response `201`

`ATMTerminal`

```json
{
  "idATM": 1,
  "codigoATM": "ATM00001",
  "tipoTerminal": "ATM",
  "idCanal": 2,
  "idAgencia": "001",
  "ubicacion": "Agencia de ejemplo",
  "estado": "A",
  "fechaInstalacion": "2026-11-10"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CODIGO_ATM_DUPLICADO` | Ya existe un terminal con ese código |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- validaciones de agencia y canal, longitudes y restricciones de campos de alta.
