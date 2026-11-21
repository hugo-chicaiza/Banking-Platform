# Inventario de registros (E0-13 · ASVS 16.1.1)

Qué se registra, dónde, quién lo lee y cuánto se guarda. Toda petición lleva un **identificador de correlación**
(`traceId`): el backend lo pone en la cabecera `X-Request-Id`, en el cuerpo de cada error (`traceId`) y en cada línea de
registro (`trace=`). El frontend lo muestra como «Código de soporte» en los mensajes de error para buscarlo aquí.

| Destino | Qué contiene | Formato | Quién lo lee | Retención |
|---|---|---|---|---|
| Registro de la aplicación (stdout → App Service `backend-dev`) | Una línea por petición: método, ruta **sin query string**, estado, duración, IP del proxy, usuario de WorkOS, agencia, roles. Errores inesperados solo con su tipo y `traceId`. | Texto (`LOG_FORMATO=texto`) o JSON (`LOG_FORMATO=json`) | Equipo de desarrollo y soporte (portal de Azure, *Log stream*) | La que fije App Service (*App Service logs*). Recomendado: 30 días |
| `SeguridadDB.Auditoria.Auditoria` | Quién, acción, objetivo, resultado, IP, roles y descripción de cada cambio y de cada acceso denegado | Tabla; solo inserción (disparador `trg_Auditoria_E008_Protegida`) | Auditor y administrador (E8-01) | Permanente |
| `Auditoria.EventoPendiente` (las dos bases) y `Auditoria.EventoDetalle` | Bandeja de salida de eventos y su detalle inmutable (E0-08) | JSON ya filtrado | El relevo; auditor | Pendientes hasta su entrega; detalle permanente |
| `SeguridadDB.Sistema.TareaEjecucion` | Inicio, fin, resultado y conteos de cada tarea programada, sin datos personales | Tabla | Administrador (E8-08) | Permanente |
| Registros del Worker de Cloudflare (proxy del frontend) | Peticiones que pasan por el proxy | Cloudflare | Administrador de la cuenta de Cloudflare | Los de la cuenta gratuita (solo en vivo) |
| Registros de GitHub Actions | Salida del CI, despliegues y respaldos (sin secretos: GitHub los oculta) | Texto | Equipo con acceso al repositorio | 90 días (valor por defecto) |

## Nunca se registra

Número de tarjeta, PIN, tokens, cookies, contraseñas, claves de API ni enlaces de invitación; tampoco el query string
(puede llevar cédulas o nombres) ni cuerpos de petición. Los módulos no los pasan al registro; como última barrera, el
formato de registro (`app/core/config/logs.py`, `enmascarar`) reemplaza:

- números de 13 a 19 dígitos que pasan la verificación Luhn → `[PAN ****1234]`;
- tokens JWT y `Bearer …` → `[token]`; claves `sk_…`/`pk_…` → `[secreto]`;
- el valor de `password`, `contraseña`, `clave`, `secret`, `token`, `api_key`, `pin` y `cookie` → `[oculto]`.

Los saltos de línea dentro de un valor se escriben como `\n` para que nadie pueda falsificar una línea (ASVS 16.4.1).

## Producción

- No existen las rutas de documentación de la API (`/api/docs`, `/api/openapi.json`), y la ruta de prueba del PIN pad
  (`/api/v1/pruebas/*`) responde 404; `tests/unit/test_registros.py` lo verifica arrancando la app con
  `APP_ENV=production`.
- La dirección de origen se toma solo de la cabecera que pone el proxy, y con `PROXY_EXIGIDO` el backend rechaza el
  tráfico que no llega por el Worker (`SoloProxyMiddleware`).

## Buscar un error

1. El usuario copia el «Código de soporte» del mensaje.
2. En el *Log stream* de App Service (o la exportación), buscar `trace=<código>` (texto) o `"traceId": "<código>"` (JSON).
3. En `Auditoria.Auditoria`, los accesos denegados llevan el mismo código en la descripción (`... trace=<código>`).
