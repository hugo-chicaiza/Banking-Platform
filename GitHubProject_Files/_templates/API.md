`<MÉTODO> /api/v1/<ruta>` · **Roles:** <ROL, ROL> · **Historia:** <X-00 (#n)> · **OpenAPI:** `<operationId>`

<Una frase: qué hace el endpoint y qué devuelve.>

| Lee | Escribe | DB |
|---|---|---|
| `Esquema.Tabla` | `Esquema.Tabla` | `usp_Procedimiento` / trigger, si aplica |

## Reglas de negocio

1. <Validación o regla, con el código de error que produce → `422 CODIGO`>

## Flujo

1. <Paso a paso del backend, incluida la transacción de DB si mueve dinero>

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idX | path | int | Sí | |

```json
{ }
```

## Response `200`

```json
{ }
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CODIGO` | <condición> (DB 51xxx) |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Reglas de datos sensibles (sin PAN/PIN en logs), si aplica

## Pendiente

- <Solo si hay>
