---
number: 139
title: "ATM-01 | POST /api/v1/atm/auth"
type: api
code: ATM-01
parent: "[[T-01 Validar tarjeta y PIN]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/139
---

`POST /api/v1/atm/auth` · **Roles:** Terminal ATM · **Historia:** T-01· **OpenAPI:** `ATM01`

Autentica una tarjeta y verifica su PIN mediante un PIN Block cifrado conforme a ISO 9564-1 formato 4 (AES-256) y el mecanismo IBM 3624 PIN Offset. Si la autenticación es correcta, abre una sesión ATM.

Durante el desarrollo se utilizarán tarjetas ficticias y un HSM simulado. Se contempla una futura integración con un HSM de pagos de Thales, siempre que el servicio seleccionado admita las operaciones necesarias.

| **Lee** | **Escribe** | **DB / Componente** |
|---|---|---|
| `ATM.ATM`, `Tarjeta.Tarjeta`, `Canal.Canal`, `Cuentas.Cuenta`, `SeguridadDB.Tarjetas.TarjetaPIN`, repositorio aislado de PAN ficticios | `SeguridadDB.Tarjetas.TarjetaPIN`, `Tarjeta.TarjetaHis`, registros de auditoría y sesión ATM | `CooperativaDB`, `SeguridadDB`, repositorio de pruebas, HSM |

## Reglas de negocio

1. El terminal ATM debe existir, estar activo y pertenecer a un canal habilitado. Debe cumplir las condiciones `RequiereTarjeta`, `RequierePin` y `RequiereTerminal` → `409 ATM_FUERA_DE_SERVICIO`.
2. La tarjeta se identificará mediante el PAN ficticio obtenido de la lectura simulada. El backend calculará `HashNumeroTarjeta` (SHA-256) para localizarla en `Tarjeta.Tarjeta`. El PAN completo no se almacenará en dicha tabla.
3. La tarjeta debe estar `Activa`, no vencida y tener `PinAsignado = 1` → `409 TARJETA_NO_ACTIVA` o `409 PIN_NO_CONFIGURADO`, según corresponda. Una tarjeta bloqueada → `423 TARJETA_BLOQUEADA`. Excepciones para una tarjeta `Generada` (A-05):
   - **Débito con PIN temporal** (`TarjetaPIN.RequiereCambio = 1`): se acepta para el primer cambio de PIN; la sesión queda restringida (regla 16).
   - **Crédito:** si ya pasaron 3 días laborables desde `FechaEmision` (`Contabilidad.FechaContable.EsDiaContable`), la tarjeta pasa a `Activa` con `TarjetaHis` (`Activacion`) después de verificar el PIN y se continúa como una tarjeta activa. Si no, `409 TARJETA_NO_ACTIVA`.
   - Cualquier otro caso de `Generada` → `409 TARJETA_NO_ACTIVA`.
4. El registro de `SeguridadDB.Tarjetas.TarjetaPIN` deberá existir, tener una asignación confirmada y encontrarse en estado `Activo`. Si está bloqueado → `423 PIN_BLOQUEADO`.
5. El PIN se capturará en el componente seguro del terminal y se transmitirá mediante un **PIN Block ISO 9564-1 formato 4 cifrado con AES-256**, utilizando TLS para la comunicación.
6. El HSM simulado procesará el PIN Block cifrado y verificará el PIN mediante **IBM 3624 PIN Offset**, utilizando el Offset registrado durante TAR-05 y los mismos parámetros de verificación.
7. La verificación utilizará la clave de generación de PIN, los datos de validación, la tabla de decimalización y la longitud del PIN definidos para IBM 3624. La clave de generación de PIN será independiente de la clave AES-256 del PIN Block.
8. Un PIN incorrecto → `401 PIN_INCORRECTO`. Cada intento fallido incrementará `IntentosFallidos` en `SeguridadDB.Tarjetas.TarjetaPIN`.
9. Se permitirán **3 intentos fallidos consecutivos por tarjeta**. Al alcanzar el límite, el PIN pasará a estado `Bloqueado`, se registrará `FechaBloqueo` y se generará evidencia de auditoría. El bloqueo impedirá nuevas autenticaciones.
10. Un PIN correcto reiniciará `IntentosFallidos = 0`. El reinicio deberá confirmarse antes de emitir la sesión.
11. La autenticación correcta emitirá un JWT de **5 minutos** (`expiresIn = 300`) con `scope=atm`, identificador de tarjeta, terminal, cuentas autorizadas y `cambioPinRequerido`. El token deberá estar firmado y validarse en las operaciones posteriores.
12. La actualización del contador, el bloqueo y el reinicio de intentos deberán realizarse de forma atómica y segura frente a solicitudes concurrentes.
13. El acceso al PAN ficticio estará restringido al entorno de pruebas y a los componentes autorizados. La referencia de clave AES recibida se validará contra la configuración del servidor.
14. No se registrarán PAN completos, PIN, PIN Blocks, PIN Offset, claves criptográficas ni tokens de sesión en logs, URLs o mensajes de error.
15. El HSM simulado será exclusivo de desarrollo y pruebas. Su sustitución por un HSM de pagos real deberá realizarse mediante una interfaz de integración, sin modificar las reglas de negocio de ATM-01.
16. **Sesión restringida:** si el PIN es temporal (`RequiereCambio = 1`, tarjeta de débito `Generada` o PIN regenerado con TAR-05), el PIN correcto emite la sesión con `cambioPinRequerido = true` y sin cuentas. Esa sesión solo sirve para ATM-06 (cambio de PIN) y ATM-09 (logout). Las demás operaciones ATM usan la dependencia `require_sesion_operativa`, que la rechaza con `403 PIN_CAMBIO_REQUERIDO`.

## Flujo

1. Validar la identidad y autorización del terminal ATM, su estado y la configuración del canal.
2. Obtener el PAN ficticio desde la lectura simulada de tarjeta, calcular su hash y localizar la tarjeta.
3. Validar estado, vencimiento y asignación del PIN de la tarjeta (incluidas las excepciones de `Generada`).
4. Consultar `SeguridadDB.Tarjetas.TarjetaPIN` y comprobar que el PIN esté confirmado, activo y no bloqueado.
5. Recibir el PIN Block ISO-4 cifrado y validar su formato y la referencia de clave autorizada.
6. Obtener el PIN Offset y los parámetros de IBM 3624 asociados a la tarjeta.
7. Solicitar al HSM simulado la verificación del PIN mediante IBM 3624 PIN Offset.
8. Si el PIN es incorrecto, incrementar atómicamente `IntentosFallidos`. Al llegar a 3, bloquear el PIN, registrar `FechaBloqueo` y generar evidencia de auditoría. Responder `401 PIN_INCORRECTO` o `423 PIN_BLOQUEADO`, según corresponda.
9. Si el PIN es correcto, reiniciar atómicamente `IntentosFallidos = 0` y confirmar la actualización.
10. Si el PIN es temporal, emitir la sesión restringida (`cambioPinRequerido = true`, sin cuentas). Si es una tarjeta de crédito `Generada` que cumplió el plazo, activarla.
11. Consultar las cuentas autorizadas y generar un JWT de sesión ATM con vigencia de 300 segundos.
12. Responder `200` con el token de sesión, el titular, las cuentas enmascaradas y `cambioPinRequerido`.

## Request

Body `AtmAuthRequest`:

| **Campo** | **Tipo** | **Req.** | **Regla** |
|---|---|---|---|
| codigoATM | string(8) | Sí | Identificador de un terminal ATM autorizado |
| idTarjeta | integer | Sí | Identificador de la tarjeta ficticia leída por el simulador |
| encryptedPinBlock | string(32) | Sí | PIN Block ISO-4 cifrado de 16 bytes, codificado en hexadecimal |
| keyReference | string | Sí | Referencia de clave AES-256 autorizada por el servidor |

```json
{
  "codigoATM": "ATM00001",
  "idTarjeta": 301,
  "encryptedPinBlock": "00112233445566778899AABBCCDDEEFF",
  "keyReference": "TEST-KEY-01"
}
```

*El PIN Block y la referencia de clave del ejemplo son ficticios. No representan un bloque válido generado a partir de un PIN.*

En el entorno de pruebas, `idTarjeta` identifica la tarjeta simulada. El backend obtendrá el PAN ficticio mediante el repositorio aislado definido en TAR-01 y comprobará su correspondencia con `HashNumeroTarjeta`. En una integración con un lector de tarjetas real, este mecanismo deberá sustituirse por un flujo de lectura y procesamiento seguro.

Los parámetros de IBM 3624 y la referencia de la clave de generación de PIN serán gestionados internamente, no enviados por el cliente.

## Response `200`

`AtmAuthResponse`

```json
{
  "sessionToken": "TOKEN_ATM_FICTICIO",
  "expiresIn": 300,
  "titular": "Cliente de ejemplo",
  "cambioPinRequerido": false,
  "cuentas": [
    {
      "idCuenta": 501,
      "numeroCuentaEnmascarado": "********0501",
      "tipoCuenta": "Ahorros"
    }
  ]
}
```

Sesión restringida (PIN temporal): el cajero debe pedir el cambio de PIN (ATM-06) antes de cualquier otra operación.

```json
{
  "sessionToken": "TOKEN_ATM_FICTICIO",
  "expiresIn": 300,
  "titular": "Cliente de ejemplo",
  "cambioPinRequerido": true,
  "cuentas": []
}
```

El token mostrado es ilustrativo. En ejecución se generará un JWT firmado, con una vigencia de 300 segundos y los permisos correspondientes a la sesión ATM.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| **HTTP** | **`code`** | **Cuándo** |
|---|---|---|
| 401 | `PIN_INCORRECTO` | El PIN no coincide (equivalente conceptual a ISO 8583, código 55) |
| 423 | `PIN_BLOQUEADO` | El PIN alcanzó el límite de intentos o ya estaba bloqueado |
| 423 | `TARJETA_BLOQUEADA` | La tarjeta se encuentra bloqueada |
| 409 | `TARJETA_NO_ACTIVA` | La tarjeta no está activa o está vencida |
| 409 | `PIN_NO_CONFIGURADO` | La tarjeta no tiene un PIN asignado |
| 409 | `PIN_NO_DISPONIBLE` | No existe una asignación de PIN confirmada o habilitada |
| 409 | `ATM_FUERA_DE_SERVICIO` | El terminal o su canal no están habilitados |
| 422 | `PIN_BLOCK_INVALIDO` | El PIN Block tiene un formato o estructura inválidos |
| 422 | `CLAVE_NO_AUTORIZADA` | La referencia de clave no está autorizada |
| 503 | `HSM_NO_DISPONIBLE` | No se puede completar la verificación criptográfica |
| 503 | `PAN_NO_DISPONIBLE` | No se puede obtener el PAN ficticio necesario para la verificación |
| 503 | `ACTIVACION_NO_CONFIRMADA` | No se pudo registrar la activación automática de una tarjeta de crédito |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores).
- [ ] Prueba de autenticación correcta y de cada error de la tabla.
- [ ] Validación de terminal, canal, tarjeta, vencimiento y estado del PIN.
- [ ] Identificación de tarjeta mediante PAN ficticio y verificación de su correspondencia con `HashNumeroTarjeta`.
- [ ] Procesamiento del PIN Block ISO-4 con AES-256 mediante el HSM simulado.
- [ ] Verificación de IBM 3624 PIN Offset generado previamente por TAR-05.
- [ ] Compatibilidad de los parámetros IBM 3624 utilizados en TAR-05 y ATM-01.
- [ ] Incremento persistente del contador de intentos fallidos.
- [ ] Bloqueo del PIN al tercer intento fallido.
- [ ] Reinicio del contador después de una autenticación correcta.
- [ ] Pruebas de intentos concurrentes sin superar el límite permitido.
- [ ] Verificación de que un PIN bloqueado no permite iniciar sesión.
- [ ] JWT firmado con `scope=atm` y vigencia de 300 segundos.
- [ ] Consulta y devolución exclusiva de cuentas autorizadas y enmascaradas.
- [ ] Sin PAN, PIN, PIN Block, PIN Offset, claves criptográficas ni tokens en logs.
- [ ] Pruebas del flujo completo con tarjetas y claves ficticias.
- [ ] Tarjeta de débito `Generada` con PIN temporal: sesión restringida sin cuentas.
- [ ] Tarjeta de crédito `Generada`: se activa solo después de 3 días laborables.
- [ ] Una sesión restringida es rechazada por las operaciones que usan `require_sesion_operativa`.

## Pendiente

- [ ] **G-02:** adaptar `SeguridadDB.Tarjetas.TarjetaPIN` para almacenar IBM 3624 PIN Offset, metadatos de verificación, contador de intentos y estado del PIN.
- [ ] Implementar la verificación IBM 3624 PIN Offset en el HSM simulado.
- [ ] Definir y documentar los parámetros de IBM 3624 compartidos con TAR-05.
- [ ] Integrar el acceso controlado al repositorio de PAN ficticios definido en TAR-01.
- [ ] Implementar la lectura simulada de tarjeta y su correspondencia con `HashNumeroTarjeta`.
- [ ] Implementar el incremento, bloqueo y reinicio atómico de `IntentosFallidos` en `SeguridadDB`.
- [ ] Definir el procedimiento autorizado de desbloqueo y su auditoría.
- [ ] Implementar la emisión y validación del JWT de sesión ATM.
- [ ] Definir el mecanismo de autenticación del terminal para evitar que un cliente no autorizado se haga pasar por un ATM.
- [ ] Implementar el registro de auditoría sin datos sensibles.
- [ ] Evaluar la integración con un HSM de pagos de Thales y confirmar la disponibilidad de operaciones ISO-4 e IBM 3624.
- [ ] ATM-02 a ATM-08 (excepto ATM-06) deben usar `require_sesion_operativa` para rechazar la sesión restringida.

### Reglas de seguridad — ATM-01

**SEC-ATM-01: Límite de intentos del PIN**

- Se permitirán 3 intentos fallidos consecutivos por tarjeta.
- Cada verificación incorrecta incrementará `IntentosFallidos` en `SeguridadDB.Tarjetas.TarjetaPIN`.
- Al alcanzar 3 intentos fallidos, el PIN quedará en estado `Bloqueado` y se registrará `FechaBloqueo`.
- Un PIN verificado correctamente reiniciará el contador a 0.
- El contador será persistente: no se reiniciará al cerrar la sesión, cambiar de terminal ni reiniciar el sistema.
- La actualización del contador y el bloqueo deberán ejecutarse de forma atómica para evitar condiciones de carrera.
- Las solicitudes concurrentes deberán serializar o coordinar la verificación por tarjeta, de forma que no puedan utilizarse intentos adicionales mientras una verificación esté en curso.

**SEC-ATM-02: Desbloqueo**

- El desbloqueo requerirá un procedimiento autorizado de recuperación o reasignación del PIN.
- El desbloqueo restablecerá el contador de intentos y registrará evidencia de auditoría.
- El vencimiento de la sesión ATM no desbloqueará automáticamente el PIN.

**SEC-ATM-03: Protección del PIN**

- El backend no recibirá el PIN en texto plano a través de la API.
- La captura y construcción del PIN Block se realizarán en un componente controlado del entorno de pruebas.
- La verificación del PIN utilizará IBM 3624 PIN Offset mediante el HSM simulado.
- No se almacenarán el PIN original ni el PIN natural.
- No se registrarán PIN, PIN Blocks, PAN completos, PIN Offset ni secretos criptográficos en logs o evidencias.
- La comunicación utilizará TLS 1.3 preferentemente, o TLS 1.2 configurado de forma segura cuando sea necesario.
- El HSM simulado no se considerará una implementación certificada para operaciones bancarias reales.

**SEC-ATM-04: Autenticación y autorización del terminal**

- Cada terminal ATM deberá autenticarse mediante un mecanismo independiente de `codigoATM`.
- `codigoATM` identificará al terminal, pero no será suficiente para demostrar su identidad.
- El backend verificará que el terminal autenticado corresponda al `codigoATM` de la solicitud.
- El terminal únicamente podrá acceder a las operaciones autorizadas para su canal.
- En una integración real se evaluará el uso de certificados de cliente y mTLS, junto con controles de autorización por terminal.

### Criterios de aceptación adicionales

- [ ] Un PIN incorrecto incrementa el contador de intentos.
- [ ] Al tercer intento fallido, el PIN queda bloqueado.
- [ ] Una autenticación correcta reinicia el contador.
- [ ] Un PIN bloqueado no permite iniciar sesión ATM.
- [ ] El bloqueo persiste entre sesiones y terminales.
- [ ] Los intentos concurrentes no permiten superar el límite.
- [ ] El desbloqueo requiere autorización y queda auditado.
- [ ] Un terminal no autenticado no puede utilizar ATM-01.
- [ ] La autenticación correcta genera una sesión ATM válida durante 300 segundos.

## Consideraciones de seguridad

La implementación utilizará un HSM simulado exclusivamente para fines académicos y de pruebas.

Se utilizará ISO 9564-1 formato 4 con AES-256 para proteger el PIN Block e IBM 3624 PIN Offset para verificar el PIN, con claves criptográficas ficticias e independientes.

El mecanismo IBM 3624 tradicional utiliza operaciones basadas en DES/3DES, mientras que ISO-4 utiliza AES-256 para el PIN Block. Estas operaciones deberán implementarse por separado.

El simulador reproducirá conceptualmente el procesamiento de PIN utilizado en sistemas bancarios, pero no constituye un HSM certificado ni garantiza el cumplimiento de ISO 9564, PCI DSS o PCI PIN Security.

Para producción se requerirán terminales y dispositivos seguros de captura del PIN, un HSM de pagos certificado, gestión segura de claves, autenticación robusta de terminales y validación de los requisitos normativos aplicables.

La futura integración con Thales dependerá de las capacidades del servicio seleccionado; no se asumirá que Luna Cloud HSM y payShield Cloud HSM ofrecen las mismas operaciones.
