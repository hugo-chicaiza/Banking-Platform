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
| `Cuentas.Cuenta`, `Canal.Canal`, `ProductosFinancieros.ProductoCanalCupo`, personalizado e historial | `Canal.CanalCupoClienteCustom`, `Canal.CuposModHis` | `Canal.trg_CanalCupoClienteCustom_Tope`, `Canal.trg_CuposModHis_Inmutable` |

## Reglas de negocio

1. Cuenta y canal deben existir: 404 `CUENTA_NO_ENCONTRADA` / `CANAL_NO_ENCONTRADO`.
2. Debe existir un cupo predeterminado para el subproducto de la cuenta y el canal: si no, 422 `CUPO_PRODUCTO_NO_CONFIGURADO`.
3. Los tres importes son estrictamente positivos, con precisión decimal(18,2), según `CK_CanalCupoClienteCustom_Cupos`. Cero, negativos y valores no representables se rechazan con 400 `DATOS_INVALIDOS` antes de guardar.
4. Coherencia: `0 < montoMaxTransaccion <= cupoDiario <= cupoMensual`; si los valores positivos incumplen el orden, 422 `CUPOS_INCONSISTENTES`.
5. Ningún importe ni la frecuencia supera el cupo del subproducto en ese canal: 422 `CUPO_SUPERA_MAXIMO_PRODUCTO` (DB 52003).
6. `maxTransaccionesDia` es un entero estricto entre 1 y 32767, compatible con smallint.
7. `fechaVigencia` es una fecha límite inclusiva en Ecuador. Omitirla o enviar null significa sin caducidad; una fecha pasada guarda un personalizado vencido y la respuesta usa el cupo predeterminado vigente.
8. El PUT crea o actualiza el personalizado con Estado='A'. Cada PUT exitoso deja exactamente una fila en `CuposModHis`, incluida la creación con anteriores nulos.
9. Usuario interno mediante `UsuarioAuditoria`, nunca desde el body. Cuenta, topes y personalizado se protegen durante la transacción; escritura, historial y respuesta se validan antes del commit.
10. La implementación respeta el esquema actual. No se permite usar un cupo cero como bloqueo ni se requiere una migración.

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
| cupoDiario | number | Sí | > 0; decimal(18,2) |
| cupoMensual | number | Sí | > 0 y >= cupoDiario; decimal(18,2) |
| montoMaxTransaccion | number | Sí | > 0 y <= cupoDiario; decimal(18,2) |
| maxTransaccionesDia | integer | Sí | Entero entre 1 y 32767 |
| fechaVigencia | string/null | No | Fecha YYYY-MM-DD de caducidad inclusiva; null no caduca |

```json
{
  "cupoDiario": 400.0,
  "cupoMensual": 5000.0,
  "montoMaxTransaccion": 200.0,
  "maxTransaccionesDia": 10,
  "fechaVigencia": null
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
  "fechaVigencia": null,
  "consumidoHoy": 100.0,
  "consumidoMes": 1200.0
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 401/403 y errores comunes:

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `DATOS_INVALIDOS` | Importe cero, negativo, precisión inválida, frecuencia inválida o campo fuera del contrato |
| 404 | `CUENTA_NO_ENCONTRADA` | No existe la cuenta de la URL |
| 404 | `CANAL_NO_ENCONTRADO` | No existe el canal de la URL |
| 422 | `CUPO_PRODUCTO_NO_CONFIGURADO` | El subproducto no define cupo para ese canal |
| 422 | `CUPO_SUPERA_MAXIMO_PRODUCTO` | Un importe o la frecuencia supera el máximo del subproducto |
| 422 | `CUPOS_INCONSISTENTES` | Los importes positivos no cumplen máximo por transacción <= diario <= mensual |
| 503 | `CUPO_EFECTIVO_NO_VERIFICABLE` | No se pudo construir una respuesta efectiva única; se revierte la operación |

## Definición de terminado

- [ ] Coincide con el OpenAPI generado por FastAPI (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

El autoservicio de clientes y el bloqueo individual de canales no forman parte de esta historia. El alcance actual corresponde a SUPERVISOR y ADMIN y usa el esquema existente.

## Implementación verificada (2026-11-04)

- Contrato adaptado a las restricciones vigentes: importes positivos decimal(18,2), frecuencia smallint positiva y topes del subproducto. El script propuesto para admitir cero se retiró; no hay migración pendiente para esta entrega.
- `trg_CanalCupoClienteCustom_Tope` valida topes y lanza 52003. No inserta historial: el backend registra una sola fila en `Canal.CuposModHis` dentro de la misma transacción.
- 52003 conserva `CUPO_EXCEDE_PRODUCTO` en la traducción global; solo CTA-08 publica `CUPO_SUPERA_MAXIMO_PRODUCTO`.
- XLOCK/HOLDLOCK sobre cuenta, HOLDLOCK sobre máximos y UPDLOCK/HOLDLOCK sobre el personalizado, con unicidad real por `IdCuenta, IdCanal`.
- Un personalizado vencido o inactivo permite que rija el del subproducto; no bloquea operaciones. PUT guarda Estado='A' y reemplaza todos los límites y la fecha de caducidad.
- `CuposModHis` guarda solo los importes anteriores/nuevos, usuario, fecha e identidad del personalizado. Frecuencia, vigencia y estado anteriores/nuevos no existen en el historial y quedan fuera de su respuesta.
- Se verifican metadatos y SQL de lectura sin escrituras permanentes en la base.
