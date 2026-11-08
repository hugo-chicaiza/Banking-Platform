---
number: 306
title: "TAR-07 | GET /api/v1/tarjetas/{idTarjeta}/sobre-pin"
type: api
code: TAR-07
parent: "[[A-05 Gestión de PIN y estado de tarjeta]]"
status: Backlog
priority: P1
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-08
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/306
---

`GET /api/v1/tarjetas/{idTarjeta}/sobre-pin` · **Roles:** ASESOR, SUPERVISOR, ADMIN · **Historia:** A-05 (#59) · **OpenAPI:** `TAR07`

Descarga, una sola vez, el **sobre de PIN** de una tarjeta de débito. Es un PDF que se entrega al cliente junto con la tarjeta para que use el PIN temporal y lo cambie en un ATM (ATM-06).

| Lee | Escribe | DB |
|---|---|---|
| `Tarjeta.Tarjeta`, almacén de sobres | Almacén de sobres, `Auditoria.Auditoria` | MongoDB (`sobres_pin`); mientras no exista, disco local (solo fuera de producción) |

## Cómo nace el sobre

- **TAR-04, al aprobar una tarjeta de débito:** el HSM genera el PIN, calcula su Offset y además entrega el PIN en claro **solo** para armar el PDF. Así funciona la impresión de sobres de PIN de un HSM real.
- **TAR-05, al regenerar el PIN de una tarjeta de débito:** se arma un sobre nuevo que **reemplaza** al anterior, porque el PIN viejo deja de servir.
- Las tarjetas de **crédito** no tienen sobre. Su PIN se asigna sin entregarse y el cliente lo pide al servicio al cliente.

## Contenido del PDF

Una página A4 con:

1. "Bienvenido a la Cooperativa {COOPERATIVA_NOMBRE}".
2. "Para conocer los beneficios de tu tarjeta ingresa a {COOPERATIVA_SITIO_WEB}" (por defecto `www.coop.com.ec`).
3. Una indicación de que es un PIN temporal y debe cambiarse en un ATM antes de usar la tarjeta.
4. Al final, **centrado**, el PIN de 4 dígitos en tamaño grande.

El PDF no lleva el número de la tarjeta (PAN) ni datos del cliente. El PIN se ve en claro: el cliente no tiene cómo descifrar nada.

## Almacenamiento

Hay un documento por tarjeta en la colección `sobres_pin`, con `_id = idTarjeta`:

| Campo | Contenido |
|---|---|
| `estado` | `Pendiente`, `Entregado` o `Reemplazado` |
| `origen` | `Aprobacion` o `Regeneracion` |
| `contenido` | El PDF cifrado con **AES-256-GCM**, clave `SOBRE_PIN_CLAVE`, dato asociado `idTarjeta` y versión. Se **borra** al entregarse |
| `version` | Número de versión del sobre |
| `creadoEn` | Fecha de creación |
| `expiraEn` | Fecha en que vence. Al entregarse se elimina el campo |
| `entregadoEn` | Fecha de entrega |
| `entregadoPor` | Usuario que lo entregó |

- **Vencimiento:** a los `SOBRE_PIN_DIAS` días (30 por defecto), un sobre no entregado se trata como inexistente y se borra. MongoDB lo hace con un índice TTL sobre `expiraEn`, y la API además lo verifica al leer, porque Cosmos DB no siempre aplica el TTL.
- **Mientras no exista MongoDB en Azure:**
  - Sin `MONGO_URI` y fuera de producción, el sobre se guarda cifrado en disco, en `SOBRE_PIN_DIR` (por defecto `Backend/.sobres_pin/`, ignorada por git).
  - Sin `MONGO_URI` en producción, o sin `SOBRE_PIN_CLAVE`, la tarjeta se aprueba igual, no se genera sobre y queda un aviso en el log.
- **Al crear MongoDB:** basta con configurar `MONGO_URI` (y opcionalmente `MONGO_DB`). El código no cambia.

## Reglas de negocio

1. La tarjeta debe existir → si no, `404 TARJETA_NO_ENCONTRADA`.
2. Si no hay sobre (crédito, vencido, nunca generado o reemplazado) → `404 SOBRE_PIN_NO_DISPONIBLE`.
3. Si ya se entregó → `409 SOBRE_PIN_ENTREGADO`. Para emitir otra hoja hay que regenerar el PIN (TAR-05).
4. **Entrega única y atómica:** la misma operación pasa el sobre a `Entregado`, borra `contenido` y registra `entregadoEn` y `entregadoPor`. Si dos asesores lo piden al mismo tiempo, solo uno recibe el PDF.
5. Si el almacén no responde → `503 SOBRE_PIN_ALMACEN_NO_DISPONIBLE`.
6. La respuesta lleva `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="sobre-pin-{idTarjeta}.pdf"` y `Cache-Control: no-store`.
7. Se audita en `Auditoria.Auditoria` como `SELECT Tarjeta.Tarjeta – TAR-07 Entrega de sobre de PIN` (Exitoso o Fallido). Nunca se registran el PIN ni el PDF.
8. El PIN, el PDF y la clave no aparecen en logs, errores ni en la auditoría.

## Flujo

1. Validar permisos y que la tarjeta exista.
2. Tomar el sobre `Pendiente` y vigente, y marcarlo `Entregado` en una sola operación.
3. Descifrar el PDF en memoria y responder `200` con el archivo.

## Request

| Parámetro | En | Tipo | Req. | Regla |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí |  |

## Response `200`

`application/pdf`: el sobre de PIN.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `TARJETA_NO_ENCONTRADA` | La tarjeta no existe |
| 404 | `SOBRE_PIN_NO_DISPONIBLE` | No hay sobre pendiente y vigente |
| 409 | `SOBRE_PIN_ENTREGADO` | El sobre ya se entregó |
| 503 | `SOBRE_PIN_ALMACEN_NO_DISPONIBLE` | El almacén de sobres no responde o no está configurado |

## Configuración

| Variable | Uso |
|---|---|
| `MONGO_URI` | Cadena de conexión de MongoDB (Azure Cosmos DB for MongoDB o Atlas). Vacía = disco local fuera de producción |
| `MONGO_DB` | Base de datos (por defecto `banking_platform`) |
| `SOBRE_PIN_CLAVE` | AES-256 en 64 hex. Vacía = no se generan sobres |
| `SOBRE_PIN_DIAS` | Vigencia de un sobre no entregado (por defecto 30) |
| `SOBRE_PIN_DIR` | Carpeta local mientras no hay MongoDB (por defecto `.sobres_pin`) |
| `COOPERATIVA_NOMBRE` | Nombre que va en el saludo |
| `COOPERATIVA_SITIO_WEB` | Sitio web que va en el PDF (por defecto `www.coop.com.ec`) |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Pendiente

- [ ] Crear MongoDB en Azure y configurar `MONGO_URI` en el App Service. Si es Cosmos DB for MongoDB (RU), verificar el soporte del índice TTL; la API igual descarta los sobres vencidos al leerlos.
- [ ] Configurar `SOBRE_PIN_CLAVE` en Azure (Key Vault).
