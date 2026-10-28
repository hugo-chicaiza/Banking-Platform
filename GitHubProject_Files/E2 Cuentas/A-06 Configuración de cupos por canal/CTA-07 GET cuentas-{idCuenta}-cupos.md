---
number: 135
title: "CTA-07 | GET /api/v1/cuentas/{idCuenta}/cupos"
type: api
code: CTA-07
parent: "[[A-06 Configuración de cupos por canal]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/135
---

`GET /api/v1/cuentas/{idCuenta}/cupos` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-06 (#62) · **OpenAPI:** `CTA07`

Cupos efectivos por canal.

| Lee | Escribe | DB |
|---|---|---|
| `Canal.CanalCupoClienteCustom`, `Canal.ProductoCanalCupo`, `Transacciones.Transaccion` | — | `Canal.fn_CupoVigente` |

## Reglas de negocio

1. Por cada canal devuelve el cupo que rige (`fn_CupoVigente`): el personalizado si está vigente; si no, el del subproducto.
2. Incluye lo consumido hoy y en el mes (de `Transacciones.Transaccion`) y el disponible.

## Flujo

1. El cliente inicia sesión en la aplicación bancaria.
2. Accede a la sección de sus cuentas.
3. Selecciona la cuenta cuyos cupos desea consultar.
4. El frontend obtiene el identificador `idCuenta`.
5. Envía la solicitud `GET /api/v1/cuentas/{idCuenta}/cupos`.
6. El backend valida la autenticación y los permisos del usuario.
7. Verifica que el cliente tenga autorización sobre la cuenta solicitada.
8. El sistema identifica el producto financiero asociado a la cuenta.
9. Consulta los cupos predeterminados definidos para sus canales.
10. Verifica si existen cupos personalizados vigentes.
11. Determina el cupo efectivo de cada canal.
12. Consulta las transacciones necesarias para determinar el consumo del cupo, si el contrato lo requiere.
13. Devuelve la información de los cupos efectivos.
14. El frontend presenta los límites de operación al cliente.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

## Response `200`

`array`

```json
[
  {
    "idCanal": 1,
    "origen": "Personalizado",
    "cupoDiario": 400.0,
    "cupoMensual": 5000.0,
    "montoMaxTransaccion": 200.0,
    "maxTransaccionesDia": 10,
    "fechaVigencia": "2026-10-27",
    "consumidoHoy": 100.0,
    "consumidoMes": 1200.0
  },
  {
    "idCanal": 2,
    "origen": "Producto",
    "cupoDiario": 1000.0,
    "cupoMensual": 10000.0,
    "montoMaxTransaccion": 500.0,
    "maxTransaccionesDia": 20,
    "fechaVigencia": null,
    "consumidoHoy": 0.0,
    "consumidoMes": 2500.0
  }
]
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- Los campos relacionados con consumo y disponibilidad deben confirmarse con el esquema `CupoEfectivo` del OpenAPI.
