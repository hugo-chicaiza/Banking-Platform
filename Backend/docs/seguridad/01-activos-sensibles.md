# 01 · Inventario de activos sensibles

Clasificación: **C4 Restringido** (datos de tarjeta y autenticación; su exposición permite fraude), **C3 Confidencial**
(datos personales y financieros de clientes y personal), **C2 Interno** (configuración, registros operativos),
**C1 Público**.

## Datos

| Activo | Clase | Dónde vive | Retención | Flujos | Protección |
|---|---|---|---|---|---|
| Número de tarjeta (PAN) | C4 | `SeguridadDB` (PAN cifrado; en desarrollo `Pruebas.PanFicticio`, solo PAN ficticios) | Vida de la tarjeta + plazo regulatorio | HSM simulado ↔ backend; nunca al navegador ni a registros | AES-256-GCM ligado al `IdTarjeta` (`core/security/hsm.py`). Huella con clave: E6-12. Enmascarado en registros (`enmascarar`) |
| PIN | C4 | Nunca se guarda en claro. Se guarda el **Offset IBM 3624** (`Tarjetas.TarjetaPIN.PINOffset`) y la referencia de la PVK | Vida de la tarjeta | PIN pad → PIN Block ISO-4 (AES-256) → HSM | El backend nunca ve el PIN en claro salvo la salida de impresión del sobre (TAR-07) |
| Sobre del PIN (PDF) | C4 | MongoDB o, solo fuera de producción, carpeta local `.sobres_pin` | Hasta su única entrega | Generación → entrega única | AES-256-GCM en reposo (`SOBRE_PIN_CLAVE`); se entrega una vez y se elimina |
| PIN Block | C4 | En tránsito, nunca persistido | — | PIN pad/ATM → backend → HSM | AES-256 por `keyReference` autorizada |
| Credenciales de terminal ATM | C4 | Archivo externo con hashes y metadatos (`ATM_TERMINAL_CREDENTIALS_*`) | Mientras el terminal esté activo | ATM → backend | Solo hashes; se relee en cada autenticación para aplicar revocaciones |
| Sesión del usuario interno | C4 | Cookie `__Host-` cifrada (Fernet) en el navegador; sesión en WorkOS | Duración de la sesión | Navegador ↔ backend (BFF) ↔ WorkOS | `HttpOnly`, `Secure`, `SameSite`, `__Host-`; el navegador no recibe tokens |
| Datos personales de clientes (identificación, nombres, direcciones, contacto, situación financiera, riesgo LAFT/PEP) | C3 | `CooperativaDB` (Clientes) | Plazo regulatorio (LOPDP y normativa SEPS) | Pantallas de asesor ↔ backend | Acceso por rol y agencia; sin query string en registros; historial por módulo |
| Datos personales del personal (usuarios internos) | C3 | `SeguridadDB.Organizacion.Usuarios` + WorkOS (identidad y contraseña) | Mientras el usuario exista + auditoría | Administrador ↔ backend ↔ WorkOS | La contraseña vive solo en WorkOS (`ClaveHash` eliminado) |
| Saldos, movimientos, asientos | C3 | `CooperativaDB` | Permanente (contabilidad) | Caja, ATM, transacciones | Transacciones SQL; auditoría; aprobación de dos personas (E0-08) |
| Documentos subidos y generados | C3 | MongoDB (`banking_platform`) | Según el módulo | Usuario → análisis de malware → almacén | AES-256-GCM (`DOCUMENTOS_CLAVE`), dato asociado = clave del documento; validación por contenido |
| Bitácora de auditoría | C3 | `SeguridadDB.Auditoria.*` | Permanente | Todos los módulos → auditoría | Solo inserción (disparador); sin PAN, PIN, tokens ni secretos |
| Registros de la aplicación | C2 | App Service (stdout) | Ver [inventario de registros](../inventario-registros.md) | Backend → App Service | Sin query string ni cuerpos; `enmascarar` como última barrera |
| Secretos de configuración | C4 | Configuración de App Service, secretos de GitHub Actions, `.env` local (nunca en el repositorio) | Hasta su rotación | — | Ver [inventario de claves](02-inventario-claves.md); gitleaks en el CI |
| Respaldos de las bases | C3/C4 | Google Drive (E0-02) | Según la política de respaldos | GitHub Actions → Drive | Cifrados antes de salir del runner |

## Recursos

| Recurso | Clase | Protección |
|---|---|---|
| Azure SQL `enquohub` (CooperativaDB, SeguridadDB) | C4 | Firewall por IP; login de la aplicación separado del administrativo; TLS |
| App Service `backend-dev` | C2 | Despliegue por OIDC desde GitHub; `PROXY_EXIGIDO` (solo tráfico del Worker) |
| Worker de Cloudflare (frontend y proxy) | C2 | Cabeceras de seguridad (`public/_headers`), secreto compartido con el backend |
| WorkOS (identidad) | C4 | Roles `org-*`; permisos generales; administración solo para org-admin |
| MongoDB (documentos y sobres) | C3/C4 | Contenido cifrado por la aplicación |

## Funciones sensibles

Emisión de tarjetas y PIN (TAR-01, TAR-04, TAR-05, TAR-07) · autenticación ATM (ATM-01) · operaciones de caja y bóveda ·
reverso de transacciones · asientos manuales · cambio de rol y de permisos (AUT-09, SEG-04/06) · configuración de la
institución y parámetros · aprobaciones de dos personas (E0-08).

## Frontend

| Elemento | Detalle |
|---|---|
| Almacenamiento del navegador | Solo `localStorage`: `enquocoop-sidebar-collapsed` (preferencia del menú) y `enquocoop-cierre-pendiente` (aviso de cierre de sesión). Ningún dato personal, token ni dato de tarjeta |
| Sesión | No hay tokens en el navegador: la sesión es una cookie `HttpOnly` del backend |
| Terceros en el navegador | Ninguno descargado en tiempo de ejecución (E0-17): fuentes y librerías empaquetadas en el build. Las páginas de inicio de sesión son de WorkOS (fuera de la app) |
| Cabeceras | CSP con hashes y sin `unsafe-inline` en scripts, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` restrictiva, HSTS (`public/_headers`, verificado por `security-headers.test.ts`) |
| Dependencias | React, React Router, TanStack Query, axios, zod, zustand, Radix UI, lucide; auditadas con `npm audit` en el CI |
