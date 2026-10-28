---
number: 99
title: "CRE-25 | POST /api/v1/creditos/{idSolicitud}/documentos"
type: api
code: CRE-25
parent: "[[CR-14 Documentos del crédito]]"
status: Backlog
priority: P3
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "5"
start_date: 2026-11-16
target_date: 2026-11-23
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/99
---

`POST /api/v1/creditos/{idSolicitud}/documentos` · **Roles:** ASESOR · **Historia:** CR-14 (#72) · **OpenAPI:** `CRE25`

Registra metadatos de un documento.

| Lee | Escribe | DB |
|---|---|---|
| — | `Credito.CreditoDocumento` | — |

## Reglas de negocio

1. Guarda solo metadatos: tipo, nombre, hash SHA-256 y ubicación. Estados: Activo, Reemplazado, Anulado.
2. Un documento nuevo del mismo tipo deja el anterior en `Reemplazado`.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idSolicitud | path | integer | Sí |  |

Body `DocumentoCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| tipoDocumento | string | Sí |  |
| nombreArchivo | string | Sí |  |
| hash | string(128) | Sí | SHA-256 o superior (>= 32 caracteres) |
| idDocumentacionPDF | integer | Sí |  |

```json
{
  "tipoDocumento": "string",
  "nombreArchivo": "string",
  "hash": "string",
  "idDocumentacionPDF": 1
}
```

## Response `201`

`Documento`

```json
{
  "idDocumento": 1,
  "tipoDocumento": "string",
  "nombreArchivo": "string",
  "hash": "string",
  "estado": "string",
  "fechaCarga": "2026-11-04T10:30:00Z"
}
```

## Errores

Formato ProblemDetails (ver F-04). Solo 400/401/403/404.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla

## Pendiente

- Dónde se almacena el archivo (la DB solo tiene metadatos).
