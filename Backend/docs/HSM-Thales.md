# Del HSM simulado a Thales

Guía para reemplazar el HSM simulado de tarjetas (TAR-01, TAR-05 y ATM-01) por un HSM de Thales. Explica qué existe hoy, qué producto de Thales sirve para qué, y qué cambiar en la base de datos, el código y Azure.

> Contexto académico: hoy se usan PAN ficticios, claves ficticias y un HSM simulado. Nada de esto es un HSM certificado ni cumple ISO 9564, PCI DSS o PCI PIN.

## 1. Qué hay hoy

| Pieza | Dónde | Qué hace |
|---|---|---|
| Interfaz `Hsm` | `app/core/security/hsm.py` | Contrato que usan las reglas de negocio. Para pasar a Thales solo hay que agregar otra implementación |
| `HsmSimulado` | mismo archivo | Implementa la interfaz en software, con claves del `.env` (`HSM_SIM_*`) |
| `obtener_hsm()` | mismo archivo | Devuelve el simulador fuera de producción. En producción lanza `HsmNoDisponible`, y entonces la API responde 503 |
| Repositorio de PAN ficticios | `SeguridadDB.Pruebas.PanFicticio` | PAN cifrado con AES-256-GCM y ligado al `IdTarjeta` |
| PIN Offset | `SeguridadDB.Tarjetas.TarjetaPIN` (`PINOffset`, `ReferenciaClavePVK`) | Offset IBM 3624 de 4 dígitos, sin PIN ni hash |
| PIN pad simulado | `POST /api/v1/pruebas/pin-block` | Arma el PIN Block ISO-4 para probar. Solo ADMIN y fuera de producción |

Las operaciones de la interfaz son:

| Método | Uso | Algoritmo |
|---|---|---|
| `cifrar_pan` / `descifrar_pan` | TAR-01 (custodia), TAR-05 y ATM-01 (leer la tarjeta) | AES-256-GCM, con `IdTarjeta` como dato asociado |
| `construir_pin_block` | PIN pad simulado | ISO 9564-1 formato 4 (AES-256) |
| `generar_offset` | TAR-05 | Abre el ISO-4, valida la fortaleza del PIN y calcula el IBM 3624 Offset con la PVK (3DES) |
| `verificar_pin` | ATM-01 | Abre el ISO-4 y compara el PIN con PIN natural + Offset |

Parámetros IBM 3624, que deben ser idénticos en TAR-05 y ATM-01 y se definen en `hsm.py`:

- **Longitud del PIN:** 4.
- **Tabla de decimalización:** `0123456789012345`.
- **Datos de validación:** los 12 dígitos del PAN a la izquierda del dígito de control, completados con `F` hasta 16 caracteres.

## 2. Qué producto de Thales sirve

Thales tiene dos familias, y **no hacen lo mismo**. Antes de programar, confirma cuál habilita la cuenta de prueba que solicitaste.

| | Luna Cloud HSM (Data Protection on Demand) | payShield (10K o payShield Cloud HSM) |
|---|---|---|
| Tipo | HSM de **propósito general** | HSM de **pagos** |
| Interfaz | PKCS#11 / JCE / CNG, con cliente de Thales | *Host commands* por TCP/TLS |
| Prueba gratuita | Normalmente sí (prueba de DPoD) | Normalmente bajo contrato o demo comercial |
| Cifrar el PAN | ✅ AES-GCM nativo | ✅ |
| ISO-4 e IBM 3624 nativos | ❌ No tiene comandos de PIN. Se pueden **emular** con primitivas AES/3DES dentro del HSM, pero el PIN queda en claro en la memoria de la app | ✅ Comandos de PIN: el PIN nunca sale del HSM |
| Válido para PCI PIN | No | Sí, con el modelo certificado |

**Recomendación:**
- Si la prueba es de **Luna Cloud HSM**, que es lo más probable: impleméntalo como en la sección 4A. Las claves pasan a vivir dentro del HSM y no se pueden exportar, y es un salto real respecto al simulador.
- Si consigues **payShield**: sección 4B.

Verifica con Thales qué firmware o versión admite **PIN Blocks ISO formato 4 (AES)** y los comandos IBM, porque varía según la versión.

## 3. Cambios en la base de datos

Todos van en la migración F-08 (y en su script de reversión).

| # | Cambio | Por qué |
|---|---|---|
| 1 | **Nueva tabla de producción** `SeguridadDB.Tarjetas.TarjetaPAN (IdTarjeta int PK, PanCifrado varbinary(256) NOT NULL, EtiquetaClave varchar(64) NOT NULL, VersionClave int NOT NULL, Algoritmo varchar(20) NOT NULL, FechaRegistro datetime2 NOT NULL DEFAULT SYSDATETIME())` | El número de tarjeta ya no se guarda: se guarda el **PAN cifrado por el HSM**, con la etiqueta y la versión de la clave para poder rotarla |
| 2 | `Pruebas.PanFicticio` **no se crea en producción**. En desarrollo puede quedarse, o migrarse a `TarjetaPAN` cuando el entorno de pruebas use Thales | Lo exige TAR-01: "repositorio deshabilitado en producción" |
| 3 | `Tarjeta.Tarjeta.HashNumeroTarjeta`: de **SHA-256 a HMAC-SHA256 con una clave del HSM** (`varbinary(32)`, mismo tamaño) | Un SHA-256 sin clave del PAN se revierte por fuerza bruta: la máscara deja unos 100.000 candidatos. Con HMAC, sin la clave del HSM no se puede |
| 4 | Recalcular `HashNumeroTarjeta` de las tarjetas que tengan su PAN custodiado | Las 4 tarjetas semilla no tienen PAN recuperable: hay que reemitirlas o marcarlas como no operables en ATM |
| 5 | `Tarjetas.TarjetaPIN`: conservar `PINOffset` y `ReferenciaClavePVK`, y guardar en `ReferenciaClavePVK` la **etiqueta** de la PVK en Thales | ATM-01 debe verificar con la misma PVK con la que TAR-05 generó el Offset |
| 6 | **Eliminar `Tarjetas.TarjetaPIN.HashPIN`** | Ya no se usa (Argon2id → IBM 3624). Va justo después de desplegar el código nuevo |
| 7 | Opcional: catálogo `Seguridad.ClaveHsm (Referencia, Proveedor, Etiqueta, Uso, Estado, FechaAlta, FechaRotacion)` | Saca las `keyReference` autorizadas del `.env` y deja trazabilidad de la rotación de claves |

Con payShield, además, las claves de trabajo (PVK, la clave de PIN Block) suelen guardarse **cifradas bajo la LMK** fuera del HSM, como *key blocks*. Hay que decidir si van en Key Vault o en la tabla del punto 7, con una columna `ClaveBajoLmk`.

## 4. Cambios en el código

### Comunes a ambos productos

1. **Configuración** (`app/core/config/settings.py`):
   - `HSM_PROVEEDOR = simulado | luna | payshield`.
   - Las credenciales y etiquetas de cada proveedor. Los secretos (contraseña del *crypto officer*, certificados) van como `SecretStr` y, en Azure, desde **Key Vault**.
2. **`obtener_hsm()`**: elige la implementación según `HSM_PROVEEDOR`. En producción no debe aceptar `simulado`.
3. **Nueva implementación** en `app/integrations/thales_hsm.py` (por ejemplo, `HsmLuna` o `HsmPayShield`) que cumpla **la misma interfaz `Hsm`**. Las reglas de TAR-01, TAR-05 y ATM-01 no cambian.
4. **Custodia del PAN** (`tarjetas/repository.py` y `service.py`):
   - Guardar y leer de `Tarjetas.TarjetaPAN` cuando el proveedor no sea `simulado`.
   - Renombrar `pan_de_prueba` → `pan_custodiado`, sin cambiar a quienes lo llaman.
   - Agregar `VersionClave` y `Algoritmo` al guardar.
5. **`HashNumeroTarjeta` con HMAC:** agregar `hsm.hmac_pan(pan) -> bytes` a la interfaz y usarlo en TAR-01 y en la búsqueda de ATM-01, en lugar de `hashlib.sha256`.
6. **PIN pad:** `/api/v1/pruebas/pin-block` **no existe en producción**. En producción, el PIN Block lo arma un componente de captura seguro, como un PIN pad o un cajero, con su propia clave. Hay que definir cómo recibe el frontend o el ATM esa clave: es una decisión de arquitectura pendiente.
7. **Pruebas:**
   - Pruebas unitarias con un doble de la interfaz `Hsm`.
   - Pruebas de integración contra la cuenta de prueba de Thales, marcadas y omitidas en el CI, como las de `tests/integration`.
   - Una prueba de compatibilidad: un Offset generado con Thales debe verificarse con Thales.

### 4A. Luna Cloud HSM (PKCS#11)

1. En DPoD, crear el servicio y la partición, descargar el **cliente de servicio** (librería PKCS#11 `libCryptoki2_64.so` más la configuración y los certificados) y crear el *crypto officer*.
2. Crear en el HSM las claves, **no exportables** y con etiqueta:
   - `pan-aes256` (AES-256: cifrado y descifrado).
   - `pin-block-aes256` (AES-256).
   - `pvk-3des` (DES3, doble o triple largo).
   - Opcional: `pan-hmac` (clave genérica para HMAC-SHA256).
3. Dependencia de Python: una librería PKCS#11, por ejemplo `python-pkcs11`. Agrégala a `requirements.in` y regenera los locks.
4. Correspondencia de operaciones:

   | Operación | Mecanismo PKCS#11 |
   |---|---|
   | `cifrar_pan` / `descifrar_pan` | `CKM_AES_GCM` (IV de 12 bytes y `IdTarjeta` como AAD, igual que hoy) |
   | Abrir ISO-4 | `CKM_AES_ECB` dos veces más un XOR con el campo PAN (el mismo algoritmo de `hsm.py`, pero con la clave dentro del HSM) |
   | PIN natural IBM 3624 | `CKM_DES3_ECB` sobre los datos de validación, y decimalización en la app |
   | `hmac_pan` | `CKM_SHA256_HMAC` |

5. **Límite:** el PIN queda en claro en la memoria de la app mientras se calcula el Offset. Es aceptable en el ámbito académico, pero hay que documentarlo; no es PCI.
6. **Azure App Service:**
   - Publicar la librería del cliente y su configuración junto a la app, o usar un contenedor.
   - Definir la variable `ChrystokiConfigurationPath`.
   - Permitir la salida de red hacia DPoD.

### 4B. payShield (host commands)

1. Conexión TCP/TLS al payShield, con un *header* por mensaje. Probar primero con el comando de diagnóstico `NC`.
2. Las claves de trabajo (PVK y clave de PIN Block) quedan cifradas bajo la LMK y se envían en cada comando.
3. Comandos que suelen usarse (confírmalos en el *Host Command Reference* de tu firmware):

   | Operación | Comando habitual |
   |---|---|
   | Pasar el PIN Block ISO-4 del PIN pad a cifrado bajo LMK | Comandos de traducción de PIN Block, como la familia `CA`/`JC`/`JE` según el formato |
   | Generar el IBM Offset de un PIN elegido por el cliente | `DE` |
   | Verificar el PIN en ATM-01 | `DA` (PIN de terminal) o `EA` (PIN de intercambio), método IBM |
   | Cifrar el PAN | Cifrado de datos con una clave de datos (según el firmware) |

4. Ventaja: el PIN nunca está en claro fuera del HSM.

## 5. Orden de migración sugerido

1. Confirmar con Thales el producto de la cuenta de prueba y si admite ISO-4 e IBM 3624 (sección 2).
2. Crear las claves y probar la conexión desde local con un script aislado.
3. Implementar `HsmLuna` o `HsmPayShield` con sus pruebas, y `HSM_PROVEEDOR=simulado` como valor por defecto.
4. Aplicar la migración de la base (sección 3, puntos 1, 3 y 5) en desarrollo.
5. Reemitir tarjetas de prueba con TAR-01 y asignarles el PIN con TAR-05 usando Thales; luego verificar con ATM-01.
6. Configurar Azure (Key Vault, red y cliente), cambiar `HSM_PROVEEDOR` y desplegar.
7. Eliminar `HashPIN` y, si aplica, `Pruebas.PanFicticio`.

## 6. Mientras tanto (simulador)

- Las variables `HSM_SIM_*` deben ser **iguales en local y en Azure**, porque comparten la base. Si cambian, los PAN y Offsets ya guardados dejan de servir.
- **Si se pierde `HSM_SIM_CLAVE_PAN`**, ningún PAN custodiado se puede recuperar. Si se pierde **`HSM_SIM_CLAVE_PVK`**, ningún PIN asignado se puede verificar. Respalda esas claves fuera del repositorio.
- **No uses nunca claves reales** en las variables `HSM_SIM_*`.
