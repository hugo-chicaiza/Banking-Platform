# Referencia de configuración

Generada con `python Backend/scripts/referencia_configuracion.py`. No lee .env ni muestra valores desplegados.
Los nombres siguen Settings; las variables se usan en MAYÚSCULAS. Vacío no habilita por sí solo la integración correspondiente.
COOPERATIVA_NOMBRE y COOPERATIVA_SITIO_WEB son respaldos opcionales antes del alta de Entidad, sin marca de ejemplo. La ausencia de marca no bloquea la configuración inicial.

| Variable | Tipo | Valor inicial de código | Descripción / contexto |
|---|---|---|---|
| `APP_ENV` | `Literal['development', 'staging', 'production']` | `'production'` | Parámetro app env |
| `APP_NAME` | `<class 'str'>` | `'banking-platform-backend'` | Parámetro app name |
| `LOG_LEVEL` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Parámetro log level |
| `LOG_FORMATO` | `Literal['texto', 'json']` | `'texto'` | E0-13: "texto" (una línea con trace=) o "json" (una línea JSON por registro) |
| `AUD_RELEVO_ALERTA_MINUTOS` | `<class 'int'>` | `10` | E0-05: minutos que un evento puede esperar en la bandeja de salida antes de que se alerte (registro AUD_RELEVO_ALERTA y evento en la bitácora) |
| `APP_HOST` | `<class 'str'>` | `'127.0.0.1'` | Puerto no estándar; local solo en loopback. En Azure: APP_HOST=0.0.0.0 y WEBSITES_PORT=APP_PORT |
| `APP_PORT` | `<class 'int'>` | `8471` | Parámetro app port |
| `LIMITE_PETICIONES_ACTIVO` | `<class 'bool'>` | `True` | Por minuto y por IP. Mientras no se configure el proxy en Azure, todos llegan con la misma IP y comparten el límite. |
| `EDITOR_ACCESOS_ACTIVO` | `<class 'bool'>` | `False` | Parámetro editor accesos activo |
| `EDITOR_FUNCIONES_ACTIVO` | `<class 'bool'>` | `False` | Parámetro editor funciones activo |
| `LIMITE_LECTURA_POR_MINUTO` | `<class 'int'>` | `300` | Parámetro limite lectura por minuto |
| `LIMITE_ESCRITURA_POR_MINUTO` | `<class 'int'>` | `60` | Parámetro limite escritura por minuto |
| `LIMITE_SENSIBLE_POR_MINUTO` | `<class 'int'>` | `5` | Parámetro limite sensible por minuto |
| `DB_DRIVER` | `<class 'str'>` | `'ODBC Driver 18 for SQL Server'` | Parámetro db driver |
| `DB_PORT` | `<class 'int'>` | `1433` | Parámetro db port |
| `DB_ENCRYPT` | `<class 'str'>` | `'yes'` | Parámetro db encrypt |
| `DB_TRUST_SERVER_CERTIFICATE` | `<class 'str'>` | `'no'` | Parámetro db trust server certificate |
| `DB_CONNECTION_TIMEOUT` | `<class 'int'>` | `30` | Parámetro db connection timeout |
| `DB_AUTH_MODE` | `Literal['sql', 'managed_identity']` | `'sql'` | Parámetro db auth mode |
| `AZURE_CLIENT_ID` | `<class 'str'>` | `''` | Parámetro azure client id |
| `COOPERATIVA_DB_SERVER` | `<class 'str'>` | `''` | Parámetro cooperativa db server |
| `COOPERATIVA_DB_NAME` | `<class 'str'>` | `'CooperativaDB'` | Parámetro cooperativa db name |
| `COOPERATIVA_DB_USER` | `<class 'str'>` | `''` | Parámetro cooperativa db user |
| `COOPERATIVA_DB_PASSWORD` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro cooperativa db password |
| `E201_SERVICIO_SQL_USER` | `<class 'str'>` | `''` | Parámetro e201 servicio sql user |
| `E201_SERVICIO_SQL_PASSWORD` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro e201 servicio sql password |
| `SEGURIDAD_DB_SERVER` | `<class 'str'>` | `''` | Parámetro seguridad db server |
| `SEGURIDAD_DB_NAME` | `<class 'str'>` | `'SeguridadDB'` | Parámetro seguridad db name |
| `SEGURIDAD_DB_USER` | `<class 'str'>` | `''` | Parámetro seguridad db user |
| `SEGURIDAD_DB_PASSWORD` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro seguridad db password |
| `MIGRACIONES_HABILITADAS` | `<class 'bool'>` | `False` | E0-01: ejecutor de migraciones. Apagado hasta que el responsable lo active. Usa el login ADMINISTRATIVO (cadena ODBC completa, secreto aparte), nunca el de la app. |
| `MIGRACIONES_ODBC_COOPERATIVA` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro migraciones odbc cooperativa |
| `MIGRACIONES_ODBC_SEGURIDAD` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro migraciones odbc seguridad |
| `ATM_HSM_AES_KEY_HEX` | `<class 'str'>` | `''` | Parámetro atm hsm aes key hex |
| `ATM_HSM_PIN_GENERATION_KEY_HEX` | `<class 'str'>` | `''` | Parámetro atm hsm pin generation key hex |
| `ATM_HSM_KEY_REFERENCE` | `<class 'str'>` | `'TEST-KEY-01'` | Parámetro atm hsm key reference |
| `ATM_JWT_PRIVATE_KEY_PEM` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | JWT ATM: clave RSA exclusiva, inyectada por configuración segura. Sin valores predeterminados de despliegue: si falta la clave, iss o aud, no se emite sesión. |
| `ATM_JWT_ISSUER` | `<class 'str'>` | `''` | Parámetro atm jwt issuer |
| `ATM_JWT_AUDIENCE` | `<class 'str'>` | `''` | Parámetro atm jwt audience |
| `ATM_TERMINAL_CREDENTIALS_FILE` | `<class 'str'>` | `''` | Archivo externo con hashes/metadatos; se relee en cada autenticación para aplicar revocaciones sin depender de la caché de Settings o del proceso. |
| `ATM_PIN_RECOVERY_ENABLED` | `<class 'bool'>` | `False` | Ejecutor independiente: no se inicia desde FastAPI. Intentos POR ejecucion, nunca un contador acumulado ni los intentos fallidos del PIN del cliente. |
| `ATM_PIN_RECOVERY_MIN_AGE_SECONDS` | `<class 'int'>` | `30` | Parámetro atm pin recovery min age seconds |
| `ATM_PIN_RECOVERY_MAX_AGE_SECONDS` | `<class 'int'>` | `1800` | Parámetro atm pin recovery max age seconds |
| `ATM_PIN_RECOVERY_BATCH_SIZE` | `<class 'int'>` | `20` | Parámetro atm pin recovery batch size |
| `ATM_PIN_RECOVERY_BUDGET_SECONDS` | `<class 'int'>` | `45` | Parámetro atm pin recovery budget seconds |
| `ATM_PIN_RECOVERY_MAX_ATTEMPTS_PER_RUN` | `<class 'int'>` | `3` | Parámetro atm pin recovery max attempts per run |
| `ATM_PIN_RECOVERY_RETRY_DELAY_SECONDS` | `<class 'float'>` | `1` | Parámetro atm pin recovery retry delay seconds |
| `WORKOS_API_KEY` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | WorkOS AuthKit (F-03), patrón BFF: el navegador solo recibe una cookie cifrada |
| `WORKOS_CLIENT_ID` | `<class 'str'>` | `''` | Parámetro workos client id |
| `WORKOS_COOKIE_PASSWORD` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Clave Fernet con la que se cifra la cookie de sesión |
| `WORKOS_REDIRECT_URI` | `<class 'str'>` | `''` | URL de GET /api/v1/auth/callback tal como la ve el navegador |
| `FRONTEND_URL` | `<class 'str'>` | `''` | Origen del FE (esquema://host[:puerto], sin ruta): redirecciones y control CSRF |
| `WORKOS_ORGANIZATION_ID` | `<class 'str'>` | `''` | Organización de WorkOS de la cooperativa (EnquoCoop): todos los usuarios internos son miembros de ella y su rol vive en esa membresía (C-05) |
| `FRONTEND_ORIGIN_REGEX` | `<class 'str'>` | `''` | Solo backend-dev, nunca producción: orígenes extra del FE (previews de PR de Cloudflare), aceptados si llegan en X-Forwarded-Host desde el Worker. Ejemplo: ^https://[a-z0-9-]+-banking-platform-front\.cuenta\.workers\.dev$ |
| `PROXY_SECRETO` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | ASVS 4.1.3 / 15.3.4: secreto compartido con el Worker de Cloudflare. Solo una petición que lo trae (X-Proxy-Secreto) puede fijar la IP del usuario (X-Cliente-Ip). Vacío (local) = se usa la IP de la conexión. Mismo valor que el secreto del Worker |
| `PROXY_EXIGIDO` | `<class 'bool'>` | `False` | True = se rechaza (403) toda petición que no venga del Worker con el secreto |
| `HSM_SIM_CLAVE_PAN` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | HSM simulado de tarjetas (app/core/security/hsm.py): claves ficticias en hex. Vacías = HSM no disponible (503). En producción nunca se usan. Deben ser las mismas en local y Azure: comparten la base donde está el PAN cifrado. |
| `HSM_SIM_CLAVE_PVK` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Parámetro hsm sim clave pvk |
| `HSM_SIM_CLAVES_PIN_BLOCK` | `dict[str, pydantic.types.SecretStr]` | `Secreto; nunca se documenta su valor` | keyReference -> clave AES-256 del PIN Block ISO-4 (64 hex), en JSON |
| `HSM_SIM_REFERENCIA_PIN_BLOCK` | `<class 'str'>` | `'TEST-KEY-01'` | La que usa el endpoint de pruebas que simula el PIN pad |
| `SOBRE_PIN_CLAVE` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Sobre de PIN de débito (TAR-07): PDF con el PIN temporal, cifrado en reposo y entregado una sola vez. Sin clave no se generan sobres. |
| `SOBRE_PIN_DIAS` | `<class 'int'>` | `30` | Parámetro sobre pin dias |
| `SOBRE_PIN_DIR` | `<class 'str'>` | `'.sobres_pin'` | Carpeta local mientras no hay MongoDB (solo fuera de producción) |
| `COOPERATIVA_NOMBRE` | `<class 'str'>` | `''` | Presentación previa al alta de Entidad; vacías = instalación sin configurar. |
| `COOPERATIVA_SITIO_WEB` | `<class 'str'>` | `''` | Parámetro cooperativa sitio web |
| `MONGO_URI` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | MongoDB (Azure Cosmos DB for MongoDB o Atlas). Vacío = sin MongoDB |
| `MONGO_DB` | `<class 'str'>` | `'banking_platform'` | Parámetro mongo db |
| `DOCUMENTOS_CLAVE` | `<class 'pydantic.types.SecretStr'>` | `Secreto; nunca se documenta su valor` | Documentos (E5-08, P4-10): contenido cifrado (AES-256-GCM) en la colección `documentos` de MongoDB; sin clave o sin MONGO_URI responde 503. |
| `DOCUMENTOS_MAX_BYTES` | `<class 'int'>` | `5242880` | Parámetro documentos max bytes |
| `WORKOS_AUDIT_USER_IDS` | `dict[str, Annotated[int, FieldInfo(annotation=NoneType, required=True, metadata=[Strict(strict=True), Ge(ge=1), Le(le=2147483647)])]]` | `Factoría dict` | Vínculos administrados por despliegue, nunca por el navegador ni por email. |
