# ATM-01: autenticación temporal del terminal simulado

Estado: implementación local autorizada; sin aprovisionamiento, despliegue ni cambios
en Azure. mTLS queda como mejora pendiente; su observador permanece deshabilitado.
No se implementa todavía el agente ATM ni se entrega una credencial al frontend.

## Contrato y orden de validación

`POST /api/v1/atm/auth`, exclusivamente HTTPS. La cabecera `X-ATM-Credential`
contiene un identificador público seguido de punto y un secreto base64url canónico
de 32 bytes aleatorios (256 bits), sin padding. Nunca colocar esta cabecera en URL,
logs, telemetría, ejemplos con valores reales ni respuestas.

El cuerpo conserva `codigoATM`, `numeroTarjeta`, `encryptedPinBlock` y
`keyReference`. Primero se validan HTTPS y la credencial; después se lee el JSON,
se comprueba la correspondencia con `codigoATM` y la configuración RSA. A continuación
se validan terminal/canal, tarjeta identificada por SHA-256 binario, PIN y cuentas.
La credencial se revalida antes de abrir SQL y antes de emitir el JWT.

La respuesta conserva `sessionToken`, `expiresIn` (300), `titular` y cuentas
enmascaradas. El JWT RS256 lleva `iss`, `aud`, `iat`, `exp`, `jti`, `scope=atm`,
`idATM`, `idTarjeta` y los identificadores de cuentas autorizadas.
La autenticación del terminal no depende del HSM ni del JWT y puede sustituirse
posteriormente por mTLS.

## Configuración necesaria antes de considerar operativo el endpoint

- `ATM_TERMINAL_CREDENTIALS_FILE`: ruta absoluta a un JSON **fuera del repositorio**,
  administrado solo por operadores autorizados. El proceso backend necesita lectura;
  solo el aprovisionador debe poder modificarlo. No hay valor predeterminado útil.
- `ATM_JWT_PRIVATE_KEY_PEM`: clave privada RSA exclusiva de ATM, al menos 2048 bits,
  suministrada mediante configuración segura; nunca por archivos versionados.
- `ATM_JWT_ISSUER` y `ATM_JWT_AUDIENCE`: valores explícitos y coherentes con los futuros
  consumidores. Su ausencia o una clave incorrecta produce 503 antes de verificar PIN.
- HTTPS efectivo en el scope ASGI. Tras terminación TLS, configurar el servidor
  para aceptar información del protocolo **solo de proxies confiables** y bloquear
  ingresos directos alternativos. No se acepta `X-Forwarded-Proto` directamente en
  la dependencia. Configurar HTTPS en el frontal y verificar el esquema recibido
  antes del despliegue; no usar confianza global en cualquier IP.
- Catálogos y datos compatibles ya provisionados: terminal/canal activo, tarjeta
  activa con cuenta habilitada, PAN custodiado, PINOffset y referencia PVK coherentes.
  No se crean ni actualizan estos datos con esta implementación.

El JSON es un objeto indexado por identificador público. Cada registro contiene
`codigoATM`, `sha256` (SHA-256 hexadecimal del secreto base64url ASCII), `enabled`,
`notBefore`, `expiresAt` (fechas ISO 8601 con zona) y `auditUserId`.
`auditUserId` debe identificar un actor interno existente y autorizado para dejar
el historial del bloqueo; no se inventa ni crea automáticamente. El registro no
contiene el secreto. Los errores nunca devuelven su contenido ni los hashes.

## Aprovisionamiento local y entrega

La herramienta `Backend/scripts/atm_terminal_credentials.py` permite `issue`,
`rotate` y `revoke`; no se ha ejecutado para terminales reales. Preparar previamente
un directorio privado fuera del checkout y otro destino privado de entrega. En
Windows aplicar ACL explícita para operador/identidad backend; el modo POSIX 0600
no sustituye las ACL. En Linux usar directorios 0700 y archivos 0600. Evitar carpetas
sincronizadas, backups indiscriminados, directorios compartidos y volcados de proceso.

Ejemplo de comandos con **marcadores que deben sustituirse**, sin material sensible:

```text
python Backend/scripts/atm_terminal_credentials.py issue --registry <ruta-absoluta-externa> --codigo-atm <codigo-8-caracteres> --audit-user-id <actor-existente> --expires-at <fecha-ISO8601-con-zona> --credential-out <archivo-privado-nuevo>
python Backend/scripts/atm_terminal_credentials.py rotate --registry <ruta-absoluta-externa> --codigo-atm <codigo-8-caracteres> --audit-user-id <actor-existente> --expires-at <fecha-ISO8601-con-zona> --credential-out <otro-archivo-privado-nuevo>
python Backend/scripts/atm_terminal_credentials.py revoke --registry <ruta-absoluta-externa> --credential-id <identificador-publico>
```

La herramienta genera el secreto con CSPRNG, escribe su hash en el registro y entrega
el material una sola vez en un archivo externo nuevo; no lo imprime. La entrega debe
transferirse al futuro agente por un canal seguro y retirarse tras importarla en su
almacén protegido. El backend solo recibe el registro de hashes. No pasar secretos
como argumentos de consola ni abrirlos en salidas registradas.

La herramienta serializa cambios con un lock y reemplaza el registro atómicamente.
Un proceso abortado puede dejar un `.lock`: verificar que no exista escritor activo
antes de retirarlo. No sobrescribir manualmente un registro durante otra operación.

## Revocación, rotación y concurrencia

Se relee el registro en cada autenticación y antes de emitir la sesión, sin caché.
Deshabilitar un registro o eliminarlo rechaza nuevas autenticaciones. Rotar admite
dos credenciales por terminal con solape máximo de 15 minutos; la anterior caduca
como máximo 15 minutos después de la rotación. Configuración ambigua, duplicada,
ilegible o con solape excesivo falla de forma segura.

La revocación es inmediata para las siguientes validaciones contra la fuente
autoritativa; no cancela retroactivamente operaciones ya verificadas ni JWT ya
emitidos, que viven hasta 300 segundos. Existe la carrera mínima entre la última
lectura y la firma. No se implementa una lista de revocación de sesiones.

**Todas las instancias y workers deben leer la misma fuente autoritativa**, con
reemplazo atómico visible para todos; copias locales independientes o propagación
eventual no cumplen la revocación inmediata. Antes de desplegar se debe verificar
esta propiedad y los permisos del volumen. Si no puede garantizarse, usar un
registro central transaccional o restringir explícitamente la ejecución a una única
instancia/fuente; no asumir consistencia por compartir el código.

El PIN mantiene UPDLOCK/ROWLOCK y actualiza intentos en la misma transacción de
SeguridadDB. Tras tres fallos se confirma el bloqueo del PIN y se bloquea la tarjeta
con historial en otra transacción de CooperativaDB usando su canal ATM. No hay
transacción distribuida: si falla este segundo paso, se devuelve 503, no se emite
JWT y el PIN permanece bloqueado; una nueva autenticación reintenta completar el
bloqueo. La escritura de historial es idempotente y no sustituye estados cancelados.

## Límites pendientes

- TAR-01/TAR-05 se alinean con `origin/develop` (`eeb0e68`, PR #295/#296,
  publicados en main por #297): custodia del PAN y asignación de Offset con
  confirmación en tres pasos. La emisión conserva el hash compartido de ATM.
  No se ejecuta el script de semilla ni se verifica el estado de datos reales.
  Antes de desplegar debe comprobarse por un procedimiento autorizado que existen
  el esquema y las columnas requeridas, y que las claves coinciden con los datos.
- El HSM compartido es un simulador para desarrollo y falla en producción hasta
  integrar un HSM real; no representa certificación bancaria ni PCI.
- La historia menciona `Transacciones.Transaccion` sin definir un movimiento de
  autenticación. No se inventa uno; el bloqueo sí registra `TarjetaHis` y el
  middleware existente audita los accesos 401/403 sin datos sensibles.
- Se conserva el limitador existente por IP/proceso. Un límite agregado entre
  réplicas y el futuro agente, mTLS y revocación anticipada de JWT quedan pendientes.
- WorkOS y sus rutas no cambian. Una sesión WorkOS no sustituye la credencial del
  terminal. El PIN pad existente en develop se incorpora con sus restricciones:
  ADMIN y fuera de producción; no sustituye ni implementa el futuro agente ATM.

## Validación local

Pruebas unitarias y de integración HTTP local con TestClient, claves RSA efímeras,
credenciales aleatorias temporales, criptografía del HSM real del simulador y SQL
simulado. Se bloquean conexiones SQL, DNS y sockets externos durante la suite.
Se cubren credenciales inválidas/duplicadas/caducadas/revocadas, HTTP y suplantación
de protocolo, asociación con terminal, revocación durante el PIN, falta de clave
JWT, ISO-4/offset/custodia, intentos y errores internos. No se ejecutan pruebas de
integración SQL ni E2E contra Azure.
