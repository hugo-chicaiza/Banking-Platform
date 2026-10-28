---
number: 86
title: "CRE-12 | POST /api/v1/creditos/solicitudes/{idSolicitud}/desembolso"
type: api
code: CRE-12
parent: "[[CR-05 Desembolso y generación de cuotas]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/86
---

`POST /api/v1/creditos/solicitudes/{idSolicitud}/desembolso` · **Roles:** ASESOR, SUPERVISOR · **Historia:** CR-05 (#31) · **OpenAPI:** `CRE12`

Desembolsa un crédito aprobado.

| Lee | Escribe | DB |
|---|---|---|
| `Credito.CreditoSolicitud`, `Cuentas.Cuenta` | `Credito.CreditoDesembolso`, `Credito.CreditoPlanAmortizacion`, `Credito.CreditoPlanDetalleRubro`, `Credito.CreditoCuota`, `Credito.CreditoResumen`, `Transacciones.Transaccion`, `Cuentas.MovimientoTransaccion`, `Cuentas.Cuenta`, `Contabilidad.*` | `Contabilidad.usp_GenerarNumeroAsiento`, `Credito.trg_CreditoCuota_Reglas`, `Credito.trg_CreditoDesembolso_Reglas`, `Cuentas.usp_AplicarMovimientoCuenta` |

## Reglas de negocio

1. Solicitud `APROBADA` → `409 SOLICITUD_NO_APROBADA` (DB 55005); aprobación dentro de `VIGENCIA_APROBACION` días → si no, 409 (DB 55006).
2. La cuenta destino es del mismo cliente y está `Activa` → `422 CUENTA_NO_PERTENECE_AL_CLIENTE` o `409 CUENTA_NO_ACTIVA`.
3. El total desembolsado no supera el monto aprobado (DB 55007); la transacción debe coincidir en cuenta, tipo y monto (DB 55008).
4. En una sola transacción de DB: `CreditoDesembolso`, `Transaccion` `Desembolso_Credito`, crédito a la cuenta, plan v1 vigente con rubros, una `CreditoCuota` por cuota, `CreditoResumen` y asiento.

## Flujo

1. Validar solicitud, vigencia y cuenta.
2. Calcular el plan definitivo (como CRE-02).
3. Registrar desembolso, transacción, movimiento, plan, cuotas, resumen y asiento en una transacción.
4. Responder 201 con el desembolso y el plan.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `DesembolsoRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuentaDesembolso | integer | Sí | Cuenta Activa del mismo cliente |
| fechaPrimerVencimiento | string | No |  |

```json
{
  "idCuentaDesembolso": 1,
  "fechaPrimerVencimiento": "2026-11-04"
}
```

## Response `201`

`Desembolso`

```json
{
  "idDesembolso": 1,
  "numeroDesembolso": "string",
  "idSolicitud": 1,
  "idCuentaDesembolso": 1,
  "montoDesembolsado": 100.0,
  "tasaNominalAnual": 100.0,
  "estado": "PENDIENTE",
  "fechaDesembolso": "2026-11-04T10:30:00Z",
  "idTransaccionDesembolso": 1,
  "numeroCuotas": 1
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `SOLICITUD_NO_APROBADA` | La solicitud no está APROBADA |
| 409 | `SOLICITUD_YA_DESEMBOLSADA` | La solicitud ya fue desembolsada |
| 409 | `CUENTA_NO_ACTIVA` | La cuenta no está Activa |
| 409 | `CUENTA_NO_PERTENECE_AL_CLIENTE` | La cuenta es de otro cliente |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Una sola transacción de DB con su asiento contable (todo o nada)
