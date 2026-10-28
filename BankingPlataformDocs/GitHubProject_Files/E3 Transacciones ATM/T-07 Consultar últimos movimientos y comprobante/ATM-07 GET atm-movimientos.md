---
number: 147
title: "ATM-07 | GET /api/v1/atm/movimientos"
type: api
code: ATM-07
parent: "[[T-07 Consultar últimos movimientos y comprobante]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "4"
start_date: 2026-11-09
target_date: 2026-11-16
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/147
---

`GET /api/v1/atm/movimientos` · **Roles:** ATM (sesión) · **Historia:** T-07 (#12) · **OpenAPI:** `ATM07`

Últimos movimientos de la cuenta de la sesión.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.MovimientoTransaccion` | — | — |

## Reglas de negocio

1. Solo cuentas de la sesión; últimos 10 movimientos, el más reciente primero.
2. Monto y tipo (C/D); sin datos de otras cuentas ni de la tarjeta.

## Flujo

1. La sesión solicita movimientos de su cuenta con el límite permitido.
2. Backend verifica acceso y consulta movimientos.
3. Devuelve un arreglo; una cuenta sin movimientos devuelve un arreglo vacío como propuesta de comportamiento.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | query | integer | Sí | Cuenta |
| limite | query | integer | No | Máx. 10 |

## Response `200`

`array`

```json
[
  {
    "idMovimiento": 1001,
    "idTransaccion": 2001,
    "numeroComprobante": "COMP-001",
    "tipoTransaccion": "Retiro",
    "tipoMovimiento": "D",
    "rolCuenta": "Origen",
    "monto": 40.0,
    "saldoAnterior": 1000.0,
    "saldoPosterior": 960.0,
    "fechaContable": "2026-11-10",
    "fechaHoraSistema": "2026-11-10T10:30:00-05:00",
    "idCanal": 2
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- orden de movimientos y valor predeterminado del límite. Propuesta: devolver [] cuando no existan movimientos.
