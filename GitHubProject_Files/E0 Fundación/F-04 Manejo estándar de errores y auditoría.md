---
number: 20
title: "F-04 | Manejo estándar de errores y auditoría"
type: task
code: F-04
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 3
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/20
---

> Como **desarrollador**, quiero **un formato estándar de errores y auditoría** para **que todos los endpoints respondan y registren igual**.

**Etapa:** 2 · **QA:** 0 d · **Tablas:** `Auditoria.Auditoria` (SeguridadDB)

## Criterios de aceptación

- [ ] Manejador global devuelve siempre ProblemDetails (`application/problem+json`)
- [ ] Errores de validación de FastAPI salen como 400 con `errors[{field, message}]`
- [ ] Los `THROW 5xxxx` de la DB se traducen con la tabla de abajo; uno sin nombre sale como `DB_<número>` y se registra en el log
- [ ] Cada respuesta lleva `traceId` = cabecera `X-Request-Id`
- [ ] Auditoría guarda usuario, acción, tabla, registro, fecha, IP y resultado (`Exitoso`/`Fallido`)
- [ ] Pruebas para 400, 401, 403, 404, 409, 422, 423 y 500

## Reglas de negocio

Formato (RFC 7807):

```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "code": "JORNADA_NO_ABIERTA",
  "detail": "La jornada no está abierta.",
  "traceId": "req-123",
  "errors": [{ "field": "monto", "message": "Debe ser mayor a 0" }]
}
```

| HTTP | Uso |
|---|---|
| 400 | JSON mal formado o campo inválido |
| 401 / 403 | Sin sesión / sin permiso |
| 404 | No existe |
| 409 | Conflicto de estado o duplicado |
| 422 | Regla de negocio |
| 423 | Bloqueado |
| 500 | Error interno, sin traza ni SQL |

Errores de la DB (`THROW 5xxxx`). Regla general: no existe → 404; estado, doble custodia o registro inmutable → 409; validación, saldo o regla → 422. Un código sin nombre propio sale como `DB_<número>`.

| Rango | Origen | HTTP | `code` destacados |
|---|---|---|---|
| 51001-51016 | Dotación de caja (`usp_RegistrarDotacionCaja`) | 404 / 409 / 422 | 51006 `JORNADA_NO_ABIERTA`, 51007 `DOBLE_CUSTODIA_VIOLADA`, 51014-51015 `BOVEDA_SALDO_INSUFICIENTE`, 51016 `CALENDARIO_SIN_FECHA` |
| 51100 | Plan de cuentas | 422 | `CUENTA_PADRE_NO_IMPUTABLE` |
| 51101-51113 | Devolución a bóveda (`usp_RegistrarDevolucionCaja`) | 404 / 409 / 422 | 51106 `DOBLE_CUSTODIA_VIOLADA`, 51111 `CUADRE_SIN_CONTEO`, 51112 `DEVOLUCION_DISTINTA_AL_CONTEO` |
| 51201-51211 | Series de billetes (`usp_RegistrarSeriesBilletes`) | 422 | `SERIES_INVALIDAS` |
| 51301-51304 | Número de asiento (`usp_GenerarNumeroAsiento`) | 422 / 500 | `ASIENTO_NUMERACION` |
| 51401-51403 | Contabilizar asiento (`usp_ContabilizarAsiento`) | 404 / 409 / 422 | 51403 `ASIENTO_DESCUADRADO` |
| 51501-51504 | Cierre de período (`usp_CerrarPeriodo`) | 404 / 409 | 51502 `PERIODO_CERRADO` |
| 51601 | Cierre diario (`usp_ValidarCierreDiario`) | 409 | `CIERRE_DIARIO_BLOQUEADO` |
| 52001-52005 | Cuentas y tarjetas (triggers) | 409 / 422 | 52001 `CLIENTE_NO_ACTIVO`, 52002 `CUENTA_NO_ACTIVA`, 52003 `CUPO_EXCEDE_PRODUCTO`, 52005 `TRANSICION_TARJETA_INVALIDA` |
| 52101-52105 | Apertura de cuenta (`usp_AbrirCuenta`) | 404 / 409 / 422 | 52102 `CLIENTE_NO_ACTIVO`, 52105 `MONTO_APERTURA_INSUFICIENTE` |
| 52201-52203 | Movimiento de cuenta (`usp_AplicarMovimientoCuenta`) | 404 / 422 | 52203 `FONDOS_INSUFICIENTES` |
| 53001-53003 | Transacciones (trigger) | 409 / 422 | 53001 `CANAL_NO_CUMPLE`, 53002 `REVERSO_NO_PERMITIDO` |
| 54001 | Cuadre de caja (trigger) | 422 | `CUADRE_NO_COINCIDE` |
| 55001-55103 | Crédito (triggers y `usp_EvaluarSolicitudCredito`) | 404 / 409 / 422 | 55005 `SOLICITUD_NO_APROBADA`, 55006 `APROBACION_VENCIDA`, 55007 `DESEMBOLSO_EXCEDE_MONTO` |
| 56001-56012 | Contabilidad (triggers) | 409 / 422 | 56003 `ASIENTO_INMUTABLE`, 56007 `PERIODO_CERRADO` |
| 57001 | Tablas históricas | 409 | `REGISTRO_INMUTABLE` |

- Los mensajes nunca exponen trazas, SQL, contraseñas, PIN, PAN ni tokens.

## Dependencias

- Bloquea: F-01 (esquema de error en el OpenAPI)
