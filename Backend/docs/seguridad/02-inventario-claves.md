# 02 · Inventario de claves y secretos

Regla: **una clave por propósito**; ninguna se reutiliza entre funciones. Los secretos de despliegue deben proceder de
un almacén gestionado aprobado. Las claves `HSM_SIM_*` son una excepción de laboratorio, solo para `development` con
bases locales y datos sintéticos; no deben configurarse en Azure, staging ni producción.

| Clave / secreto (configuración) | Propósito | Algoritmo | Longitud | Origen | Rotación |
|---|---|---|---|---|---|
| `HSM_SIM_CLAVE_PAN` | Cifrar PAN sintético | AES-256-GCM, dato asociado = `IdTarjeta` | 256 bits (64 hex) | Generada para laboratorio; no es una clave gestionada | No usar en despliegues; migrar mediante proveedor aprobado antes de cualquier dato real |
| `HSM_SIM_CLAVE_HMAC_PAN` | Búsqueda exacta de PAN sintético sin hash vulnerable a diccionario | HMAC-SHA-256; clave independiente de `HSM_SIM_CLAVE_PAN` | 256 bits (64 hex) | Generada para laboratorio; no es una clave gestionada | `ReferenciaClaveHuella` + `VersionClaveHuella` y backfill local verificado; rotación real requiere proveedor aprobado |
| `HSM_SIM_CLAVE_PVK` | PVK para el **PIN Offset IBM 3624** | 3DES (TDEA) | 112/168 bits (32 o 48 hex) | Generada por el equipo (simulado) | Con el HSM real |
| `HSM_SIM_CLAVES_PIN_BLOCK` (JSON `keyReference → clave`; la de pruebas: `HSM_SIM_REFERENCIA_PIN_BLOCK`) | PIN Block ISO 9564-1 formato 4 | AES-256 | 256 bits | Generada por el equipo (simulado) | Agregar una referencia nueva y retirar la anterior |
| `SOBRE_PIN_CLAVE` | Cifrar el sobre del PIN en reposo | AES-256-GCM | 256 bits | Generada por el equipo | Anual o ante sospecha; los sobres viven poco |
| `DOCUMENTOS_CLAVE` | Cifrar documentos en MongoDB | AES-256-GCM | 256 bits | Generada por el equipo | Anual; requiere re-cifrado o convivencia de versiones |
| `ATM_JWT_PRIVATE_KEY_PEM` | Firmar la sesión del cajero automático | RSA (JWT RS256) | ≥ 2048 bits | Generada por el equipo | Anual; publicar la pública nueva antes de retirar la anterior |
| `ATM_HSM_AES_KEY_HEX`, `ATM_HSM_PIN_GENERATION_KEY_HEX` | Operaciones ATM con el HSM simulado | AES | 256 bits | Generada por el equipo (simulado) | Con el HSM real |
| `WORKOS_COOKIE_PASSWORD` | Cifrar la cookie de sesión (BFF) | Fernet (AES-128-CBC + HMAC-SHA256) | 32 bytes | Generada por el equipo | Anual; cerrar sesiones al rotar |
| `WORKOS_API_KEY` | Llamar a la API de WorkOS | Token del proveedor | — | WorkOS (Dashboard) | Ante sospecha o salida de una persona con acceso |
| `PROXY_SECRETO` | Probar que la petición viene del Worker de Cloudflare | Secreto compartido | ≥ 32 bytes | Generado por el equipo | Semestral; en el Worker y el backend a la vez |
| Clave HMAC de confirmación de catálogos | Token sin estado de confirmación (`catalogos/confirmacion.py`) | HMAC-SHA256 | 256 bits | **Derivada** de `WORKOS_COOKIE_PASSWORD` con la etiqueta `confirmacion-catalogos:` (SHA-256) | Rota junto con `WORKOS_COOKIE_PASSWORD`. Pendiente: secreto propio para cumplir «una clave por propósito» sin derivación |
| `COOPERATIVA_DB_PASSWORD`, `SEGURIDAD_DB_PASSWORD` | Login de la aplicación en Azure SQL | — | ≥ 16 caracteres | Azure SQL | Semestral |
| Login administrativo de SQL (migraciones, respaldos) | Solo migraciones (E0-01) y respaldos (E0-02); nunca la aplicación | — | — | Azure SQL | Semestral; solo como secreto protegido del pipeline |
| `MONGO_URI` | Conexión a MongoDB | — | — | Proveedor de MongoDB | Semestral |
| `GDRIVE_SA_JSON`, `BACKUP_PASSPHRASE` | Subir respaldos a Google Drive y cifrarlos (E0-02) | Cuenta de servicio de Google; AES-256 (cifrado del respaldo) | — | Google Cloud; generada por el responsable | La frase **también se guarda fuera de GitHub**: sin ella no se restaura |
| Credenciales OIDC de despliegue (`AZUREAPPSERVICE_*`) | GitHub Actions → Azure | OIDC (sin secreto de larga duración) | — | Azure AD | Gestionadas por Azure |

## Excepción documentada: offset con 3DES

El **PIN Offset IBM 3624** usa por definición una PVK **3DES**. Es la única clave 3DES del sistema y se mantiene por
compatibilidad con el método estándar de verificación de PIN de la red. Controles: la PVK es exclusiva de esa función,
el offset por sí solo no revela el PIN, y el PIN Block viaja con AES-256 (ISO-4). Se retira cuando el HSM de pagos
real asuma la verificación.

## HSM simulado

`app/core/security/hsm.py` **no es un HSM certificado** (no cumple PCI DSS ni PCI PIN): existe solo para
desarrollo y pruebas con claves ficticias y PAN sintéticos. `obtener_hsm` lo rechaza fuera de `development`; staging y
producción deben fallar cerrados hasta que exista una integración aprobada con HSM/gestión de claves. No se debe
presentar el adaptador local como certificado ni configurar sus claves en App Service.
