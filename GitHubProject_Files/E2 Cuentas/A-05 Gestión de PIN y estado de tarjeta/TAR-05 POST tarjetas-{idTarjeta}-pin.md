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

Regenera el PIN de una tarjeta (reposición): el HSM genera un PIN nuevo y su IBM 3624 PIN Offset. Sirve cuando el cliente olvidó el PIN o cuando el PIN quedó bloqueado por intentos (SEC-ATM-02).

El PIN inicial ya no se asigna con esta API: se genera automáticamente al aprobar la tarjeta (TAR-04). Ni el asesor ni el administrador conocen ni envían el PIN.

Durante el desarrollo se utiliza un HSM simulado con claves ficticias. Se contempla una futura integración con un HSM de pagos de Thales, condicionada a la disponibilidad de las operaciones criptográficas necesarias.

| **Lee** | **Escribe** | **DB / Componente** |
|---|---|---|
| `Tarjeta.Tarjeta`, repositorio aislado de PAN ficticios | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis`, `SeguridadDB.Tarjetas.TarjetaPIN` | `CooperativaDB`, `SeguridadDB`, repositorio de pruebas, HSM |

## Reglas de negocio

1. La tarjeta debe estar en `Aprobada`, `Generada`, `Activa`, `Inactiva` o `Bloqueada` → si no (`Solicitada` o un estado terminal), `409 PIN_NO_PERMITIDO`.
2. El HSM genera un PIN aleatorio de 4 dígitos no trivial (sin repetidos ni secuencias) y calcula su **IBM 3624 PIN Offset**, con los mismos parámetros que ATM-01 (datos de validación, tabla de decimalización, longitud y PVK). El PIN no sale del HSM.
3. El PAN ficticio se obtiene mediante el mecanismo controlado de pruebas definido en TAR-01.
4. **Débito:** el PIN nuevo es temporal (`RequiereCambio = 1`) y se entrega impreso (canal no simulado). En el siguiente uso del ATM, ATM-01 abre una sesión restringida que solo permite cambiar el PIN (ATM-06).
5. **Crédito:** el PIN se asigna sin entregarse (`RequiereCambio = 0`); el cliente lo pide al servicio al cliente (no simulado).
6. Regenerar reemplaza el Offset anterior, reinicia `IntentosFallidos = 0`, deja el PIN en estado `Activo` y borra `FechaBloqueo`. **No cambia el estado de la tarjeta**: una tarjeta `Bloqueada` se desbloquea aparte con TAR-04.
7. Se marca `PinAsignado = 1` y se inserta `TarjetaHis` (`CambioPin`, “Regeneración de PIN”) sin información sensible.
8. El Offset se confirma primero en `SeguridadDB` y luego se registra en `CooperativaDB`. Si falla CooperativaDB, el PIN nuevo ya quedó vigente: se responde `503 PIN_ASIGNACION_NO_CONFIRMADA` y se puede repetir la operación (genera otro PIN).
9. El PIN, el PAN completo, el PIN Offset y las claves criptográficas no aparecen en logs, respuestas ni mensajes de error.

## Flujo

1. Validar permisos, existencia de la tarjeta y su estado.
2. Obtener el PAN ficticio mediante el repositorio controlado de pruebas.
3. Pedir al HSM simulado un PIN nuevo y su IBM 3624 PIN Offset.
4. Guardar en `SeguridadDB.Tarjetas.TarjetaPIN` el Offset, `RequiereCambio`, `Estado = 'Activo'` e `IntentosFallidos = 0`, y confirmar.
5. Marcar `PinAsignado = 1` e insertar `TarjetaHis` (`CambioPin`) en `CooperativaDB`.
6. Responder `204`.

## Request

| **Parámetro** | **En** | **Tipo** | **Req.** | **Regla** |
|---|---|---|---|---|
| idTarjeta | path | integer | Sí | Tarjeta existente en un estado que admite PIN |

Sin body.

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| **HTTP** | **`code`** | **Cuándo** |
|---|---|---|
| 404 | `TARJETA_NO_ENCONTRADA` | La tarjeta de la URL no existe |
| 409 | `PIN_NO_PERMITIDO` | La tarjeta está `Solicitada` o en un estado terminal |
| 503 | `HSM_NO_DISPONIBLE` | No se puede completar el procesamiento criptográfico |
| 503 | `PAN_NO_DISPONIBLE` | No se puede obtener el PAN ficticio |
| 503 | `PIN_ASIGNACION_NO_CONFIRMADA` | El PIN se guardó en `SeguridadDB` pero no se pudo registrar en `CooperativaDB` |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores).
- [ ] Prueba de regeneración correcta y de cada error de la tabla.
- [ ] El PIN generado nunca es trivial y es verificable por ATM-01 con el Offset guardado.
- [ ] `RequiereCambio = 1` en débito y `0` en crédito.
- [ ] La regeneración desbloquea el PIN y reinicia los intentos.
- [ ] Sin PAN completo, PIN, PIN Offset ni claves criptográficas en logs o respuestas.

## Pendiente

- [ ] Canal de entrega del PIN de débito (hoja impresa con la tarjeta) y solicitud del PIN de crédito por servicio al cliente: no se simulan. En producción, el HSM de pagos imprime el PIN (PIN mailer) sin que nadie lo vea.
- [ ] Evaluar la integración con un HSM de pagos de Thales y confirmar que el servicio seleccionado admite la generación de PIN aleatorio, ISO-4 e IBM 3624 PIN Offset.
- [ ] Adaptar la interfaz del HSM para permitir sustituir el simulador por un proveedor externo sin modificar las reglas de negocio.

## Consideraciones de seguridad

La implementación utiliza un HSM simulado con fines exclusivamente académicos y de pruebas.

El PIN se genera dentro del HSM y nunca se expone a la API ni a los usuarios del sistema. La verificación posterior (ATM-01) usa IBM 3624 PIN Offset con una PVK 3DES, independiente de la clave AES-256 del PIN Block ISO 9564-1 formato 4 que envía el cajero.

El simulador reproduce conceptualmente estas operaciones, pero no constituye un HSM bancario certificado ni garantiza el cumplimiento de ISO 9564, PCI DSS o PCI PIN Security.

Para producción se requerirán un HSM de pagos certificado, impresión segura del PIN, gestión segura de claves y validación de los requisitos normativos aplicables.
