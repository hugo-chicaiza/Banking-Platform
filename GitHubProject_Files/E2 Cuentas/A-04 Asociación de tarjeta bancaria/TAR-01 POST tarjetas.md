---
number: 129
title: "TAR-01 | POST /api/v1/tarjetas"
type: api
code: TAR-01
parent: "[[A-04 Asociación de tarjeta bancaria]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/129
---

`POST /api/v1/tarjetas` · **Roles:** ASESOR, ADMIN · **Historia:** A-04 · **OpenAPI:** `TAR01`

Emite una tarjeta asociada a una cuenta y genera los datos necesarios para su posterior asignación y verificación del PIN.

La implementación utiliza PAN ficticios y un HSM simulado durante el desarrollo. Se contempla una futura integración con un HSM de pagos de Thales, siempre que el servicio seleccionado admita las operaciones requeridas.

| **Lee** | **Escribe** | **DB / Componente** |
|---|---|---|
| `Cuentas.Cuenta`, `ProductosFinancieros.Producto`, `ProductosFinancieros.SubProducto`, `Tarjeta.BIN` | `Tarjeta.Tarjeta`, `Tarjeta.EnviosTarjeta`, `Tarjeta.TarjetaHis`, repositorio aislado de PAN ficticios | `CooperativaDB`, repositorio de pruebas |

**Validación adicional:** `Tarjeta.trg_Tarjeta_Reglas` (DB 52004).

## Reglas de negocio

1. La cuenta debe estar `Activa` y pertenecer al cliente → `409 CUENTA_NO_ACTIVA`.
2. El producto debe ser de tipo `Tarjeta` → `422 PRODUCTO_NO_ES_TARJETA`. El asesor elige el subproducto (p. ej. `TDB001-MC` Débito Mastercard o `TCR001-MC` Crédito Mastercard, listados en CAT-07 con `tipo=Tarjeta`): debe pertenecer al producto → `422 SUBPRODUCTO_NO_ENCONTRADO`, y estar activo con un BIN activo → `422 BIN_INVALIDO`. El `tipoTarjeta` debe coincidir con el del subproducto (`TDB…` = Débito, `TCR…` = Crédito, ver CAT-07) → `422 TIPO_TARJETA_NO_COINCIDE`. El BIN de la tarjeta es el del subproducto (DB 52004). El formulario pide primero el tipo y ofrece solo sus subproductos (`GET /catalogos/productos?tipoTarjeta=…`).
3. El sistema generará un PAN ficticio con el BIN correspondiente y un dígito de control válido, calculado mediante el algoritmo de Luhn. Se utilizarán exclusivamente rangos de prueba autorizados; no se emitirán PAN de tarjetas bancarias reales.
4. En `Tarjeta.Tarjeta` únicamente se almacenarán `TokenTarjeta`, `NumeroEnmascarado` y `HashNumeroTarjeta` (SHA-256) como representaciones del número de tarjeta. El PAN completo no se almacenará en esta tabla ni se devolverá en las respuestas.
5. **Custodia del PAN para pruebas:** el PAN ficticio se conservará en un repositorio aislado de desarrollo y pruebas, asociado a `IdTarjeta`, con acceso restringido a los componentes autorizados. Este repositorio no estará habilitado en producción.
6. El PAN ficticio estará disponible mediante una interfaz controlada para TAR-05 y ATM-01:
   - **TAR-05:** construcción del PIN Block conforme a ISO 9564-1 formato 4 (AES-256) y obtención de los datos de validación necesarios para IBM 3624 PIN Offset.
   - **ATM-01:** simulación de lectura de tarjeta, identificación de la tarjeta y verificación del PIN mediante IBM 3624 PIN Offset.
7. El `TokenTarjeta` identificará la tarjeta dentro del sistema. No se asumirá que permite recuperar el PAN sin un mecanismo de correspondencia autorizado.
8. Una tarjeta de extensión requiere una tarjeta titular válida → `422 EXTENSION_REQUIERE_TITULAR`.
9. La tarjeta se registrará como solicitud: estado `Solicitada`, `PinAsignado = 0` y `FechaSolicitud` con la fecha actual. `FechaEmision` se registra provisionalmente con la fecha actual (la columna es obligatoria) y se actualiza al pasar a `Generada` (TAR-04). El PIN no se asigna aquí: se genera automáticamente al aprobar la tarjeta (TAR-04). Si `requiereEnvio = true`, se creará un registro en `Tarjeta.EnviosTarjeta` con estado `PENDIENTE` y la dirección correspondiente.
10. Las claves criptográficas utilizadas para proteger el PIN Block y generar o verificar el PIN Offset serán independientes y estarán bajo responsabilidad del componente HSM, no de TAR-01.
11. El PAN completo, el PIN, los PIN Blocks, las claves criptográficas y otros secretos no aparecerán en logs, URLs ni respuestas de la API.
12. La emisión deberá garantizar la consistencia entre el registro de la tarjeta y el repositorio de PAN ficticios, evitando tarjetas emitidas sin un PAN recuperable para las pruebas y registros huérfanos.

## Flujo

1. Validar la cuenta, el producto, el BIN y las condiciones de emisión.
2. Generar un PAN ficticio utilizando un rango de prueba autorizado, el BIN correspondiente y un dígito de control válido.
3. Generar `TokenTarjeta`, `NumeroEnmascarado` y `HashNumeroTarjeta` (SHA-256).
4. Registrar la tarjeta con estado `Solicitada`, `PinAsignado = 0` y `FechaSolicitud`.
5. Registrar el envío, cuando corresponda, y el historial en `Tarjeta.TarjetaHis`.
6. Asociar el PAN ficticio a `IdTarjeta` en el repositorio aislado de pruebas.
7. Confirmar que la tarjeta y su PAN ficticio quedaron correctamente asociados. Ante un fallo parcial, aplicar el mecanismo de recuperación definido para evitar inconsistencias.
8. Responder `201` con los datos de la tarjeta, sin exponer el PAN completo.

## Request

Body `TarjetaCreate`:

| **Campo** | **Tipo** | **Req.** | **Regla** |
|---|---|---|---|
| idCuenta | integer | Sí | Cuenta activa del cliente |
| idProducto | integer | Sí | Producto tipo Tarjeta |
| idSubProducto | integer | Sí | Subproducto del producto (define el BIN): CAT-07 `subproductos` |
| tipoTarjeta | Debito \| Credito | Sí | |
| nombreTarjeta | string(26) | Sí | Nombre impreso: lo que admite el grabado de la tarjeta física (`Tarjeta.NombreTarjeta varchar(26)`); letras, espacios, punto, guion y apóstrofo |
| esExtension | boolean | No | |
| idTarjetaTitular | integer | No | Obligatorio si `esExtension = true` |
| requiereEnvio | boolean | No | |
| direccionEnvio | string(250) | No | Obligatorio si `requiereEnvio = true` |
| idCiudadEnvio | integer | No | |

```json
{
  "idCuenta": 501,
  "idProducto": 4,
  "idSubProducto": 3,
  "tipoTarjeta": "Debito",
  "nombreTarjeta": "MARIA MENDOZA",
  "esExtension": false,
  "requiereEnvio": false
}
```

## Response `201`

`Tarjeta`

```json
{
  "idTarjeta": 301,
  "tokenTarjeta": "tok_tarjeta_301",
  "numeroEnmascarado": "4540 12** **** 3456",
  "tipoTarjeta": "Debito",
  "nombreTarjeta": "MARIA MENDOZA",
  "idCliente": 125,
  "idCuenta": 501,
  "idProducto": 3,
  "estadoActual": "Solicitada",
  "pinAsignado": false,
  "fechaSolicitud": "2026-10-26",
  "fechaResolucion": null,
  "fechaEmision": "2026-10-26",
  "fechaExpiracion": "2031-10-26"
}
```

Los datos son ficticios. El token mostrado es ilustrativo y no representa un mecanismo de tokenización de producción.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| **HTTP** | **`code`** | **Cuándo** |
|---|---|---|
| 409 | `CUENTA_NO_ACTIVA` | La cuenta no está activa o no cumple las condiciones de emisión |
| 422 | `PRODUCTO_NO_ES_TARJETA` | El producto no es de tipo Tarjeta |
| 422 | `SUBPRODUCTO_NO_ENCONTRADO` | El subproducto no existe o no pertenece al producto |
| 422 | `BIN_INVALIDO` | El subproducto está inactivo o no tiene un BIN activo |
| 422 | `TIPO_TARJETA_NO_COINCIDE` | `tipoTarjeta` no corresponde al subproducto elegido |
| 422 | `EXTENSION_REQUIERE_TITULAR` | Una extensión necesita una tarjeta titular válida |
| 503 | `PAN_NO_DISPONIBLE` | No se pudo completar la generación o custodia del PAN ficticio |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores).
- [ ] Prueba del caso exitoso y de cada error de la tabla.
- [ ] Generación de PAN ficticios con BIN de prueba y dígito de control válidos.
- [ ] Almacenamiento exclusivo del token, número enmascarado y hash del PAN en `Tarjeta.Tarjeta`.
- [ ] Repositorio aislado de PAN ficticios implementado y asociado a `IdTarjeta`.
- [ ] Acceso al PAN completo restringido a los componentes autorizados de pruebas.
- [ ] Disponibilidad controlada del PAN ficticio para TAR-05 y ATM-01.
- [ ] Pruebas que comprueben que el PAN completo no aparece en respuestas, logs ni en `Tarjeta.Tarjeta`.
- [ ] Sin PIN, PIN Blocks, contraseñas, claves criptográficas ni tokens sensibles en logs.
- [ ] Pruebas de recuperación ante fallos durante la emisión y custodia del PAN ficticio.
- [ ] Repositorio de PAN ficticios deshabilitado en producción.

## Pendiente

- [ ] Implementar el repositorio aislado de PAN ficticios, con acceso restringido a los componentes autorizados de desarrollo y pruebas.
- [ ] Integrar el acceso controlado al PAN ficticio desde TAR-05 para la construcción del PIN Block ISO-4 y la obtención de los datos de validación de IBM 3624.
- [ ] Implementar la simulación de lectura de tarjeta para ATM-01, utilizando el PAN ficticio asociado.
- [ ] Definir los parámetros de IBM 3624 que dependerán de los datos de la tarjeta, garantizando que TAR-05 y ATM-01 utilicen los mismos datos de validación y criterios de derivación.
- [ ] Definir e implementar el mecanismo de consistencia y recuperación ante fallos entre la emisión de la tarjeta y la custodia del PAN ficticio.
- [ ] Evaluar la integración futura con un HSM de pagos de Thales, verificando previamente la disponibilidad de operaciones ISO-4 e IBM 3624 PIN Offset.
- [ ] Para producción, sustituir el repositorio de pruebas por un mecanismo seguro de emisión, tokenización y custodia del PAN, compatible con los requisitos aplicables de PCI DSS.

## Consideraciones de seguridad

Esta implementación corresponde exclusivamente a un entorno académico de desarrollo y pruebas.

Se utilizarán PAN ficticios, claves de prueba y un HSM simulado para reproducir conceptualmente operaciones de emisión y autenticación de tarjetas bancarias.

La protección del PIN Block mediante ISO 9564-1 formato 4 (AES-256) y la verificación mediante IBM 3624 PIN Offset se implementarán en TAR-05 y ATM-01, respectivamente.

El uso de un HSM simulado no constituye una implementación certificada ni garantiza el cumplimiento de ISO 9564, PCI DSS o PCI PIN Security.

La futura integración con Thales dependerá de las capacidades del servicio seleccionado. Un HSM criptográfico de propósito general no necesariamente dispone de las funciones específicas de un HSM de pagos.

Para un entorno de producción se requerirán mecanismos de emisión y custodia de tarjetas adecuados, dispositivos seguros de captura del PIN, un HSM de pagos certificado, gestión segura de claves y validación de los requisitos normativos aplicables.
