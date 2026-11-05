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
| `Cuentas.Cuenta`, `Canal.Canal`, `Canal.CanalCupoClienteCustom`, `ProductosFinancieros.ProductoCanalCupo`, `Transacciones.Transaccion`, `Transacciones.TipoTransaccion` | — | `Canal.fn_CupoVigente` |

## Reglas de negocio

1. Verifica que la cuenta exista; si no, 404 `CUENTA_NO_ENCONTRADA`.
2. Por cada canal con configuración devuelve el cupo que rige mediante `Canal.fn_CupoVigente`: personalizado activo con fecha nula o no vencida; en otro caso, el del subproducto.
3. `FechaVigencia` es la fecha límite inclusiva en Ecuador. Un personalizado inactivo o vencido no bloquea el canal: se utiliza el predeterminado.
4. Los orígenes SQL `CUENTA`/`SUBPRODUCTO` se representan como `Personalizado`/`Producto`.
5. Incluye consumo diario y mensual de débitos normales completados, igual que el procedimiento de autorización. Los importes son Decimal/Money y la ausencia de movimientos produce cero.
6. El contrato devuelve límites y consumo; no incluye campos de disponibilidad ni bloqueo por canal.
7. Roles internos efectivos ASESOR, SUPERVISOR y ADMIN. Consulta sin DML ni commit.

## Flujo

1. El usuario interno inicia sesión y selecciona una cuenta.
2. El frontend envía `GET /api/v1/cuentas/{idCuenta}/cupos`.
3. El backend valida la sesión, el rol y la existencia de la cuenta.
4. Obtiene los límites efectivos por canal mediante la función de la base, que resuelve el subproducto y la vigencia del personalizado.
5. Calcula el consumo diario y mensual con el reloj de Ecuador y rangos sobre FechaHoraSistema.
6. Devuelve los cupos efectivos y consumos para que el usuario interno los consulte.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |

## Response `200`

`array<CupoEfectivo>`

```json
[
  {
    "idCanal": 1,
    "origen": "Personalizado",
    "cupoDiario": 400.0,
    "cupoMensual": 5000.0,
    "montoMaxTransaccion": 200.0,
    "maxTransaccionesDia": 10,
    "fechaVigencia": null,
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

- [ ] Coincide con el OpenAPI generado por FastAPI (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

El contrato vigente se documenta en el OpenAPI generado por FastAPI con `CupoEfectivo`. Campos de disponibilidad y autoservicio quedan fuera de esta entrega; no son requisitos pendientes de los endpoints actuales.

## Implementación verificada (2026-11-04)

- La tabla real es `ProductosFinancieros.ProductoCanalCupo`, relacionada mediante
  `Cuenta.IdSubProducto = ProductoCanalCupo.IdSubProducto`, junto con `IdCanal`.
- `Canal.fn_CupoVigente(int, int)` es una función tabular: prioriza origen `CUENTA` activo
  con fecha nula o **mayor o igual al día actual de Ecuador**; si no, usa `SUBPRODUCTO`.
  Se traducen a `Personalizado`/`Producto`. `fechaVigencia` es la fecha límite inclusiva;
  una fecha pasada ya está vencida. No es una fecha de inicio.
- Se devuelve cada canal para el que la función proporciona cupo, incluidos canales inactivos
  si tienen configuración. No se inventa un cupo para canales sin configuración.
- Consumo igual a `Transacciones.usp_AutorizarOperacion`: solo `Estado='Completada'`,
  `TipoOperacion='Normal'` y `TipoTransaccion.Naturaleza='D'`. Rechazadas, pendientes,
  reversadas, reversos y créditos no consumen. Se suma `Monto`, sin agregar comisiones.
- El reloj es SQL Server en Ecuador. Rango mensual desde el primer día hasta mañana,
  exclusivo; rango diario desde hoy hasta mañana. No se transforma `FechaHoraSistema`
  en el predicado. Sin movimientos los consumos son cero y se conserva Decimal/Money.
- CTA-07 y CTA-08 usan una sola consulta y un solo constructor de `CupoEfectivo`.
- No se encontró `openapi.yaml` ni un esquema autoritativo anterior de `CupoEfectivo` en el
  repositorio. Se conserva el contrato de límites y consumo; no se añaden campos de disponibilidad.
- Roles internos efectivos ASESOR/SUPERVISOR/ADMIN. No existe rol CLIENTE ni vínculo de
  propiedad WorkOS-cliente; el flujo de autoservicio exige definir esa autorización aparte.
- Sin DML ni commit; cuenta inexistente devuelve 404 `CUENTA_NO_ENCONTRADA`.
- Índice existente `IX_Transaccion_Cuenta_Fecha` usa `IdCuenta, IdFechaContable`, no la marca
  temporal. Evaluar un índice por cuenta/canal/FechaHoraSistema según planes y volumen real.
