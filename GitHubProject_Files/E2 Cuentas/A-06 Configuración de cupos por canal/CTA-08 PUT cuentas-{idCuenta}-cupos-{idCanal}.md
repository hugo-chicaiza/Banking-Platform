---
number: 136
title: "CTA-08 | PUT /api/v1/cuentas/{idCuenta}/cupos/{idCanal}"
type: api
code: CTA-08
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/136
---

`PUT /api/v1/cuentas/{idCuenta}/cupos/{idCanal}` · **Roles:** SUPERVISOR, ADMIN · **Historia:** A-06 (#62) · **OpenAPI:** `CTA08`

Define o cambia el cupo personalizado.

| Lee | Escribe | DB |
|---|---|---|
| `ProductosFinancieros.ProductoCanalCupo` | `Canal.CanalCupoClienteCustom`, `Canal.CuposModHis` | `Canal.trg_CanalCupoClienteCustom_Tope`, `Canal.trg_CuposModHis_Inmutable` |

## Reglas de negocio

1. Ningún valor supera el cupo del subproducto en ese canal → `422 CUPO_SUPERA_MAXIMO_PRODUCTO` (DB 52003).
2. Coherencia: `montoMaxTransaccion` <= `cupoDiario` <= `cupoMensual` → si no, `422 CUPOS_INCONSISTENTES`.
3. Cada cambio deja una fila en `CuposModHis` (inmutable) con valor anterior, nuevo y usuario.

## Flujo

1. Validar topes y coherencia.
2. Crear o actualizar el cupo personalizado e insertar el historial en una transacción.
3. Responder 200 con el cupo vigente.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |
| idCanal | path | integer | Sí |  |

Body `CupoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| cupoDiario | number | Sí |  |
| cupoMensual | number | Sí | >= cupoDiario |
| montoMaxTransaccion | number | Sí | <= cupoDiario |
| maxTransaccionesDia | integer | Sí | > 0 |
| fechaVigencia | string | No |  |

```json
{
  "cupoDiario": 400.0,
  "cupoMensual": 5000.0,
  "montoMaxTransaccion": 200.0,
  "maxTransaccionesDia": 10,
  "fechaVigencia": "2026-10-27"
}
```

## Response `200`

`CupoEfectivo`

```json
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
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `CUPO_SUPERA_MAXIMO_PRODUCTO` | Supera el cupo del subproducto en ese canal |
| 422 | `CUPOS_INCONSISTENTES` | Máximo por transacción > diario > mensual |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- El cliente no tiene rol en el sistema: solo SUPERVISOR y ADMIN cambian cupos (A-06 decía 'Como cliente').
