---
number: 182
title: "CLI-01 | GET /api/v1/clientes/validar-identificacion"
type: api
code: CLI-01
parent: "[[C-02 Validación del documento (cédula, RUC, pasaporte) y dup]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/182
---

`GET /api/v1/clientes/validar-identificacion` · **Roles:** ASESOR, ADMIN · **Historia:** C-02 (#42) · **OpenAPI:** `CLI01`

Valida formato del documento y si ya existe.

| Lee | Escribe | DB |
|---|---|---|
| `Clientes.Cliente` | — | — |

## Reglas de negocio

1. Cédula: 10 dígitos con dígito verificador módulo 10. RUC: 13 dígitos terminados en `001`. Pasaporte: 5 a 13 caracteres alfanuméricos (`CK_Cliente_Identificacion`).
2. Responde 200 siempre que los parámetros lleguen; el resultado va en `valido` y `existe` (si existe, incluye `idCliente`).
3. No escribe nada; CLI-02 repite la validación al crear.

## Flujo

1. Validar formato según `tipoDocumento`.
2. Buscar la identificación en `Clientes.Cliente`.
3. Responder `{ valido, existe, idCliente?, mensaje }`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| tipoDocumento | query | string | Sí | C/R/P |
| identificacion | query | string | Sí | Documento |

## Response `200`

`ValidacionIdentificacion`

```json
{
  "valida": true,
  "existe": true,
  "idCliente": 1,
  "mensaje": "mensaje"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
