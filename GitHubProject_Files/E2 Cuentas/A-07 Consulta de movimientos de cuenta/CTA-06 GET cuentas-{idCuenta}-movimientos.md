---
number: 138
title: "CTA-06 | GET /api/v1/cuentas/{idCuenta}/movimientos"
type: api
code: CTA-06
parent: "[[A-07 Consulta de movimientos de cuenta]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/138
---

`GET /api/v1/cuentas/{idCuenta}/movimientos` · **Roles:** ASESOR, CAJERO, SUPERVISOR, ADMIN · **Historia:** A-07 (#123) · **OpenAPI:** `CTA06`

Movimientos de la cuenta.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.MovimientoTransaccion`, `Transacciones.Transaccion` | — | — |

## Reglas de negocio

1. Rango `desde`/`hasta` obligatorio coherente (`desde` <= `hasta`) → si no, 400.
2. Cada movimiento trae tipo (C/D), monto, saldo anterior y posterior, transacción y comprobante; los reversos aparecen como movimientos propios.
3. Paginado (máx. 100), orden por fecha descendente; sin movimientos → `items: []`.

## Flujo

1. El asesor accede a la sección de consulta de cuentas bancarias.
2. Busca la cuenta mediante `CTA-02`.
3. Selecciona la cuenta cuyos movimientos desea consultar.
4. El frontend obtiene el identificador `idCuenta`.
5. El asesor establece el rango de fechas y, opcionalmente, el tipo de transacción.
6. El frontend envía la solicitud `GET /api/v1/cuentas/{idCuenta}/movimientos`.
7. El backend valida la autenticación y los permisos del usuario.
8. El sistema verifica la existencia de la cuenta y el alcance de acceso.
9. Consulta los movimientos en `Cuentas.MovimientoTransaccion` y la información correspondiente en `Transacciones.Transaccion`.
10. Aplica los filtros de fecha y tipo de transacción.
11. Ordena y pagina los resultados.
12. Devuelve los movimientos encontrados.
13. El frontend presenta el estado de cuenta al asesor.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |
| desde | query | string | No | Fecha contable desde |
| hasta | query | string | No | Fecha contable hasta |
| tipoTransaccion | query | string | No | Tipo |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageMovimientoCuenta`

```json
{
  "items": [
    {
      "idMovimiento": 1003,
      "idTransaccion": 2003,
      "numeroComprobante": "COMP-000203",
      "tipoTransaccion": "DEPOSITO",
      "tipoMovimiento": "C",
      "rolCuenta": "Destino",
      "monto": 200.0,
      "saldoAnterior": 150.0,
      "saldoPosterior": 350.0,
      "fechaContable": "2026-10-26",
      "fechaHoraSistema": "2026-10-26T10:30:00-05:00",
      "idCanal": 1
    },
    {
      "idMovimiento": 1002,
      "idTransaccion": 2002,
      "numeroComprobante": "COMP-000202",
      "tipoTransaccion": "RETIRO",
      "tipoMovimiento": "D",
      "rolCuenta": "Origen",
      "monto": 50.0,
      "saldoAnterior": 200.0,
      "saldoPosterior": 150.0,
      "fechaContable": "2026-10-25",
      "fechaHoraSistema": "2026-10-25T14:15:00-05:00",
      "idCanal": 1
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 2
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
