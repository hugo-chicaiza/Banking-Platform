---
number: 128
title: "CTA-05 | PATCH /api/v1/cuentas/{idCuenta}/estado"
type: api
code: CTA-05
parent: "[[A-03 Bloqueo o cierre de cuenta]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "2"
start_date: 2026-10-26
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/128
---

`PATCH /api/v1/cuentas/{idCuenta}/estado` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-03 (#23) · **OpenAPI:** `CTA05`

Cambia el estado (bloquear, inactivar, cerrar, reactivar).

| Lee | Escribe | DB |
|---|---|---|
| Cuenta, desembolsos y plan/cuotas/pagos/mora vinculados | `Cuentas.Cuenta`, auditoría F-04 | Bloqueos transaccionales y restricciones vigentes |

## Reglas de negocio

1. Transiciones públicas: ACTIVA ⇄ INACTIVA · ACTIVA → BLOQUEADA → ACTIVA · ACTIVA/INACTIVA → CERRADA (terminal) → si no, `409 TRANSICION_INVALIDA`.
2. Cerrar exige `Saldo = 0` y `SaldoRetenido = 0` (`CK` de la DB) → `409 CUENTA_CON_SALDO`; y sin desembolsos PENDIENTE ni deuda verificable de créditos DESEMBOLSADO vinculados por IdCuentaDesembolso → `409 CUENTA_CON_CREDITO_VIGENTE`. Fija `FechaCierre`.
3. `motivo` obligatorio, sin blancos ni controles, máximo 300 caracteres; usuario interno de la sesión mediante UsuarioAuditoria. Se rechazan campos extra.
4. Bloquear la cuenta no cambia sus tarjetas, pero solo una cuenta `Activa` puede debitarse (DB 52002).

## Flujo

1. Validar la transición y las condiciones de cierre.
2. Actualizar `Estado` (y `FechaCierre`) y registrar auditoría (F-04).
3. Responder 200.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

Body `CuentaEstadoUpdate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| estado | ACTIVA \| INACTIVA \| BLOQUEADA \| CERRADA | Sí |  |
| motivo | string | Sí | No vacío; máximo 300 caracteres |

```json
{
  "estado": "BLOQUEADA",
  "motivo": "Bloqueo solicitado por el titular de la cuenta."
}
```

## Response `200`

`Cuenta`

```json
{
  "idCuenta": 1,
  "numeroCuenta": "100200300401",
  "idCliente": 1,
  "idAgencia": "001",
  "idProducto": 1,
  "tipoCuenta": "Ahorro",
  "idMoneda": 840,
  "saldo": 150.0,
  "saldoRetenido": 150.0,
  "estado": "BLOQUEADA"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `CUENTA_NO_ENCONTRADA` | No existe la cuenta |
| 503 | `DEUDA_CLIENTE_NO_VERIFICABLE` | El plan, cuotas o pagos no permiten comprobar la deuda; se revierte |
| 409 | `CUENTA_CON_SALDO` | La cuenta tiene saldo o saldo retenido |
| 409 | `CUENTA_CON_CREDITO_VIGENTE` | Hay un desembolso pendiente o deuda vigente vinculada a la cuenta de desembolso |
| 409 | `TRANSICION_INVALIDA` | El cambio de estado no está permitido |

## Definición de terminado

- [ ] Coincide con el OpenAPI generado por FastAPI (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla


## Implementación verificada (2026-11-04)

- Contrato de respuesta compartido con CTA-03: USD 840 y estados públicos en mayúsculas.
  `FechaCierre` se persiste, pero no se añaden fechas ni `saldoDisponible` al modelo `Cuenta`.
- `CuentaEstadoUpdate` rechaza campos extra. `motivo` se recorta, no admite blancos ni controles
  y tiene máximo 300 caracteres, reservando espacio en los 500 de la descripción F-04.
- La cuenta se lee con `XLOCK, HOLDLOCK`; saldo, retenido y estado se validan dentro de la
  transacción. Desembolsos y deuda usan `UPDLOCK, HOLDLOCK`, incluyendo rangos sin filas.
- Relación real: `Credito.CreditoDesembolso.IdCuentaDesembolso -> Cuentas.Cuenta.IdCuenta`.
  Es una cuenta de desembolso; no se encontró un vínculo separado de garantía contra Cuenta.
  Si «respaldar» exige otra relación jurídica, se necesita definirla antes de ampliar esta regla.
  `PENDIENTE` impide cerrar por precaución; `REVERSADO` no respalda deuda. Para `DESEMBOLSADO`
  se reutiliza la regla de CLI-06: resumen y plan vigentes, cuotas, pagos, abonos y mora.
  Un plan incompleto devuelve 503 `DEUDA_CLIENTE_NO_VERIFICABLE`; no se presume deuda cero.
- `FechaCierre` usa el reloj SQL en `SA Pacific Standard Time`, igual que los defaults reales.
- Autorización efectiva mediante `require_roles`; usuario interno mediante `UsuarioAuditoria`.
  Auditoría F-04 guarda anterior, nuevo, motivo, usuario, IP de conexión y traceId en éxito/fallo.
  Es independiente y de mejor esfuerzo, como el mecanismo existente de F-04.
- La lectura final se valida antes del commit; cualquier fallo previo revierte la operación.
- 404 `CUENTA_NO_ENCONTRADA` si falta la cuenta. No se modifican tarjetas.
- No hay módulo Python de créditos. La regla compartida permanece en `clientes.service` hasta
  extraer ese dominio. Un futuro flujo de desembolso debe validar también el estado de cuenta;
  los bloqueos de CTA-05 cubren las validaciones hasta su commit, no operaciones futuras.
