---
number: 133
title: "TAR-05 | POST /api/v1/tarjetas/{idTarjeta}/pin"
type: api
code: TAR-05
parent: "[[A-05 Gestión de PIN y estado de tarjeta]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/133
---

`POST /api/v1/tarjetas/{idTarjeta}/pin` · **Roles:** ASESOR, ADMIN · **Historia:** A-05 · **OpenAPI:** `TAR05`

Asigna el PIN inicial de una tarjeta mediante un PIN Block cifrado conforme a ISO 9564-1 formato 4 (AES-256) y un mecanismo de verificación IBM 3624 PIN Offset.

Durante el desarrollo se utilizará un HSM simulado con claves ficticias. Se contempla una futura integración con un HSM de pagos de Thales, condicionada a la disponibilidad de las operaciones criptográficas necesarias.

| **Lee** | **Escribe** | **DB / Componente** |
|---|---|---|
| `Tarjeta.Tarjeta`, `SeguridadDB.Tarjetas.TarjetaPIN`, repositorio aislado de PAN ficticios | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis`, `SeguridadDB.Tarjetas.TarjetaPIN` | `CooperativaDB`, `SeguridadDB`, repositorio de pruebas, HSM |

## Reglas de negocio

1. Solo se permite la asignación inicial cuando `PinAsignado = 0` y no existe una asignación previa confirmada → `409 PIN_YA_ASIGNADO`.
2. El PIN debe contener exactamente 4 dígitos. Se rechazarán secuencias y dígitos repetidos (1234, 0000) → `422 PIN_DEBIL`.
3. El PIN se capturará mediante un componente seguro y se transmitirá utilizando un PIN Block cifrado conforme a **ISO 9564-1 formato 4, con AES-256**. La comunicación utilizará TLS.
4. El PAN ficticio asociado a la tarjeta se obtendrá mediante el mecanismo controlado de pruebas definido en TAR-01. Se utilizará para las operaciones ISO-4 y para obtener los datos de validación definidos para IBM 3624, sin almacenarlo en claro en `Tarjeta.Tarjeta`.
5. El HSM simulado procesará el PIN Block ISO-4 y generará un **IBM 3624 PIN Offset** asociado a la tarjeta. El Offset se almacenará en `SeguridadDB.Tarjetas.TarjetaPIN` para permitir la verificación posterior del PIN durante ATM-01.
6. IBM 3624 utilizará una clave de generación de PIN independiente de la clave AES-256 utilizada para el PIN Block. Las claves serán ficticias y exclusivas del entorno de pruebas.
7. TAR-05 y ATM-01 utilizarán los mismos parámetros de IBM 3624: datos de validación, tabla de decimalización, longitud del PIN y referencias de claves. El Offset no será reutilizado para otras tarjetas.
8. No se almacenarán el PIN original, el PIN natural ni el PIN Block descifrado. El PIN Offset no se incluirá en respuestas ni logs.
9. Tras completar correctamente la asignación, se marcará `PinAsignado = 1`, se registrará el Offset y el estado del PIN en `SeguridadDB.Tarjetas.TarjetaPIN`, y se insertará `TarjetaHis` (`CambioPin`) sin información sensible.
10. La asignación se coordinará entre `CooperativaDB` y `SeguridadDB` mediante operaciones idempotentes y mecanismos de recuperación ante fallos. Una asignación incompleta no podrá habilitar el uso del PIN.
11. El PIN, el PAN completo, el PIN Block, el PIN Offset y las claves criptográficas no aparecerán en logs, respuestas ni mensajes de error.
12. La referencia de clave recibida en la solicitud deberá validarse contra una configuración autorizada del servidor. No se permitirá seleccionar claves arbitrarias desde el cliente.

## Flujo

1. Validar permisos, existencia de la tarjeta, `PinAsignado = 0` y ausencia de una asignación previa confirmada.
2. Obtener el PAN ficticio mediante el repositorio controlado de pruebas definido en TAR-01.
3. Capturar el PIN en el componente seguro y comprobar que cumple la política de longitud y fortaleza.
4. Construir y cifrar el PIN Block ISO-4 utilizando el PAN y la clave AES-256 autorizada.
5. Recibir el PIN Block cifrado y validar su formato y la referencia de clave autorizada.
6. Enviar al HSM simulado el PIN Block cifrado, los datos de validación y los parámetros de IBM 3624 para generar el PIN Offset.
7. Registrar el Offset y sus metadatos de verificación en `SeguridadDB.Tarjetas.TarjetaPIN`, inicialmente sin habilitar el PIN.
8. Actualizar `PinAsignado = 1` en `Tarjeta.Tarjeta` e insertar `TarjetaHis` (`CambioPin`).
9. Confirmar la habilitación del PIN en `SeguridadDB` una vez verificada la consistencia entre ambas bases. Si ocurre un fallo parcial, mantener la asignación sin habilitar y aplicar el procedimiento de recuperación.
10. Responder `204` únicamente cuando la asignación esté confirmada.

## Request

| **Parámetro** | **En** | **Tipo** | **Req.** | **Regla** |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí | Tarjeta existente sin PIN asignado |

Body `PinAsignar`:

| **Campo** | **Tipo** | **Req.** | **Regla** |
|---|---|---|---|
| encryptedPinBlock | string(32) | Sí | PIN Block ISO-4 cifrado de 16 bytes, codificado en hexadecimal |
| keyReference | string | Sí | Referencia de clave AES-256 autorizada por el servidor |

```json
{
  "encryptedPinBlock": "00112233445566778899AABBCCDDEEFF",
  "keyReference": "TEST-KEY-01"
}
```

*Los valores del ejemplo son ficticios y no representan un PIN Block válido generado a partir de un PIN.*

Los parámetros de IBM 3624 y la referencia de la clave de generación de PIN serán gestionados por el componente HSM y la configuración interna del servidor, no por el cliente.

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| **HTTP** | **`code`** | **Cuándo** |
|---|---|---|
| 409 | `PIN_YA_ASIGNADO` | La tarjeta ya tiene una asignación de PIN confirmada |
| 409 | `PIN_ASIGNACION_EN_PROCESO` | Existe una asignación pendiente que todavía no puede completarse |
| 422 | `PIN_DEBIL` | PIN secuencial, repetido o no permitido |
| 422 | `PIN_BLOCK_INVALIDO` | PIN Block con formato o estructura inválidos |
| 422 | `CLAVE_NO_AUTORIZADA` | La referencia de clave no está autorizada |
| 503 | `HSM_NO_DISPONIBLE` | No se puede completar el procesamiento criptográfico |
| 503 | `PIN_ASIGNACION_NO_CONFIRMADA` | No se pudo confirmar la asignación entre ambas bases de datos |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores).
- [ ] Prueba de asignación inicial correcta y de cada error de la tabla.
- [ ] Verificación de que no se permite asignar el PIN dos veces.
- [ ] Validación de longitud y fortaleza del PIN.
- [ ] Construcción y procesamiento correcto del PIN Block ISO-4 con AES-256.
- [ ] Generación de IBM 3624 PIN Offset mediante el HSM simulado.
- [ ] Almacenamiento del Offset y sus metadatos de verificación asociados a `IdTarjeta`.
- [ ] Compatibilidad entre la generación del Offset en TAR-05 y su verificación en ATM-01.
- [ ] Validación de referencias de claves contra la configuración autorizada del servidor.
- [ ] Pruebas de recuperación ante fallos entre `CooperativaDB` y `SeguridadDB`.
- [ ] Pruebas que confirmen que una asignación incompleta no permite utilizar el PIN.
- [ ] Sin PAN completo, PIN, PIN Block, PIN Offset ni claves criptográficas en logs o respuestas.
- [ ] Pruebas del flujo ISO-4 e IBM 3624 con PAN y claves ficticias.

## Pendiente

- [ ] **G-02:** adaptar `SeguridadDB.Tarjetas.TarjetaPIN` para almacenar el IBM 3624 PIN Offset, su estado y los metadatos necesarios para la verificación.
- [ ] Implementar la generación y verificación de IBM 3624 PIN Offset en el HSM simulado, utilizando exclusivamente claves ficticias.
- [ ] Definir y documentar los parámetros de IBM 3624: datos de validación, tabla de decimalización, longitud del PIN y referencias de claves.
- [ ] Integrar el acceso controlado al repositorio de PAN ficticios definido en TAR-01.
- [ ] Implementar el componente de captura y construcción del PIN Block ISO-4 para el entorno de pruebas.
- [ ] Implementar un flujo de asignación de PIN coordinado entre `CooperativaDB` y `SeguridadDB`, con estados pendientes, operaciones idempotentes y recuperación ante fallos.
- [ ] Definir el mecanismo de gestión y protección de las claves criptográficas ficticias del simulador.
- [ ] Evaluar la integración con un HSM de pagos de Thales y confirmar que el servicio seleccionado admite ISO-4 e IBM 3624 PIN Offset.
- [ ] Adaptar la interfaz del HSM para permitir sustituir el simulador por un proveedor externo sin modificar las reglas de negocio.

## Consideraciones de seguridad

La implementación utilizará un HSM simulado con fines exclusivamente académicos y de pruebas.

Se empleará ISO 9564-1 formato 4 con AES-256 para proteger el PIN Block y el mecanismo IBM 3624 PIN Offset para la verificación del PIN. Ambos mecanismos utilizarán claves criptográficas independientes y ficticias.

IBM 3624 tradicional utiliza operaciones criptográficas basadas en DES/3DES para obtener el PIN natural y calcular el Offset. Esto es independiente del cifrado AES-256 utilizado por ISO-4.

El simulador reproducirá conceptualmente estas operaciones, pero no constituye un HSM bancario certificado ni garantiza el cumplimiento de ISO 9564, PCI DSS o PCI PIN Security.

Para producción se requerirán dispositivos seguros de captura del PIN, un HSM de pagos certificado, gestión segura de claves y validación de los requisitos normativos aplicables.

La futura integración con Thales dependerá de las capacidades efectivamente disponibles en el servicio seleccionado. No se asumirá que Luna Cloud HSM y payShield Cloud HSM ofrecen las mismas operaciones bancarias.
