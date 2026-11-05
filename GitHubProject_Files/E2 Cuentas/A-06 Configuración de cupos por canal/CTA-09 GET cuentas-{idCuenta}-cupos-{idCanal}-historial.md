---
number: 137
title: "CTA-09 | GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial"
type: api
code: CTA-09
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/137
---

`GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial` · **Roles:** SUPERVISOR, AUDITOR, ADMIN · **Historia:** A-06 (#62) · **OpenAPI:** `CTA09`

Historial de cambios de cupo.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `Canal.Canal`, `Canal.CanalCupoClienteCustom`, `Canal.CuposModHis` | — | — |

## Reglas de negocio

1. Verifica cuenta y canal: 404 `CUENTA_NO_ENCONTRADA` / `CANAL_NO_ENCONTRADO` si falta alguno.
2. Filtra por cuenta y canal mediante `CuposModHis.IdCanalCupoCliente -> CanalCupoClienteCustom.IdCanalCupo`.
3. Orden predeterminado `FechaModificacion DESC, IdCupoModHis DESC` y paginación: page >= 1, pageSize entre 1 y 100, default 1/20.
4. Sort permitido: `fechaModificacion,asc|desc` e `idCupoModHis,asc|desc`; SQL estático con parámetros ligados. Un sort inválido produce 400 `SORT_INVALIDO`.
5. Preserva total en páginas vacías. Sin personalizado o sin cambios devuelve una lista vacía.
6. Devuelve únicamente las columnas reales del historial, con fecha local presentada como -05:00.
7. Roles internos efectivos SUPERVISOR, AUDITOR y ADMIN. No hay escrituras ni commit.

## Flujo

1. Un usuario interno con rol SUPERVISOR, AUDITOR o ADMIN inicia sesión y selecciona la cuenta y el canal.
2. El frontend envía `GET /api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial`.
3. El backend valida la sesión, el rol, cuenta, canal, paginación y ordenamiento.
4. Consulta el historial enlazado al personalizado de esa cuenta y canal.
5. Devuelve `PageCupoHistorial`, incluido total aunque la página esté vacía.
6. El frontend presenta los valores anteriores/nuevos, usuario y fecha de modificación.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idCuenta | path | integer | Sí |  |
| idCanal | path | integer | Sí |  |
| page | query | integer | No | Página (desde 1) |
| pageSize | query | integer | No | Tamaño (máx. 100) |
| sort | query | string | No | Campo,asc/desc |

## Response `200`

`PageCupoHistorial`

```json
{
  "items": [
    {
      "idCupoModHis": 103,
      "cupoDiarioAnterior": 300.0,
      "cupoDiarioNuevo": 400.0,
      "cupoMensualAnterior": 4000.0,
      "cupoMensualNuevo": 5000.0,
      "montoMaxTxAnterior": 150.0,
      "montoMaxTxNuevo": 200.0,
      "modificadoPor": 125,
      "fechaModificacion": "2026-10-26T15:30:00-05:00"
    },
    {
      "idCupoModHis": 102,
      "cupoDiarioAnterior": 500.0,
      "cupoDiarioNuevo": 300.0,
      "cupoMensualAnterior": 5000.0,
      "cupoMensualNuevo": 4000.0,
      "montoMaxTxAnterior": 200.0,
      "montoMaxTxNuevo": 150.0,
      "modificadoPor": 125,
      "fechaModificacion": "2026-10-20T10:15:00-05:00"
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

- [ ] Coincide con el OpenAPI generado por FastAPI (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla


## Implementación verificada (2026-11-04)

- Filtro inequívoco real: `CuposModHis.IdCanalCupoCliente -> CanalCupoClienteCustom.IdCanalCupo`,
  y de allí `IdCuenta, IdCanal`. La FK y la unicidad del personalizado están verificadas.
  No existen `IdCuenta` ni `IdCanal` directamente en la tabla histórica.
- Allowlist de sort: `fechaModificacion,asc|desc`, `idCupoModHis,asc|desc`.
  Predeterminado `FechaModificacion DESC, IdCupoModHis DESC`. ORDER BY con CASE y
  parámetros ligados; nunca se interpolan campos o direcciones.
- Una consulta con CTE y LEFT JOIN al total preserva `total` incluso fuera de rango.
  `page=1`, `pageSize=20`, límites 1..100; parámetros repetidos/desconocidos se rechazan.
- Se verifica cuenta y canal aunque no exista personalizado: se permite historial vacío.
  Recursos ausentes: 404 `CUENTA_NO_ENCONTRADA` / `CANAL_NO_ENCONTRADO`.
- Fechas datetime2 locales se presentan con offset -05:00, siguiendo defaults de la BD.
  Importes anteriores/nuevos conservan null cuando no existen valores históricos.
- Roles efectivos SUPERVISOR/AUDITOR/ADMIN; no hay autoservicio ni propiedad autenticada
  cliente-cuenta definidos. Sin escrituras ni commit.
- El historial solo cubre las columnas existentes del ejemplo: no se fabrican frecuencia,
  vigencia ni IP. El trigger `trg_CuposModHis_Inmutable` impide UPDATE/DELETE (57001).
