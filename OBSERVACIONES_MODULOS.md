# Observaciones para clientes, cuentas y contabilidad

Revisión del 2026-11-03 sobre `develop`. Compara cada módulo con lo que ya cumplen catálogos y
tarjetas (errores F-04, logs, auditoría, ASVS nivel 2). No se tocó código de estos módulos: cada
autor corrige el suyo. Las reglas completas están en `Backend/TreeFolderStructure.md`.

## Qué usar de `app/core`

- **Router:** `APIRouter(..., route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR)`.
- **Errores de negocio:** `problema(status, code, message)` de `core/api/errors.py`, en lugar de
  un `_problema` propio. El log de cada rechazo ya lo hace `ProblemDetailsRoute`.
- **Errores `THROW 5xxxx` de la BD:** se agregan a `_DB_ERRORES` en `core/api/errors.py`. Sin
  `try/except` ni tablas propias: el router los traduce solo y nunca muestra el SQL.
- **IP del usuario:** `ip_cliente(request.scope)` de `core/api/middleware.py`.
- **Auditoría:** `audit.registrar(...)` de `core/security/audit.py`.
- **Logs:** solo `logger = logging.getLogger(__name__)`. Cada petición ya queda registrada.

**Regla de códigos:** un `code` por causa. "No existe" y "no está activo" nunca comparten code:
404 si falta el recurso de la URL, 422 `<ENTIDAD>_NO_ENCONTRADA` si falta un id del cuerpo. La
tabla de errores de la tarea es el mínimo; si falta un caso, agréguenlo a la tarea.

## Para todos

Mientras no exista F-03, `require_auth` no valida nada y en producción cualquiera puede llamar
las rutas de clientes y cuentas, incluidas las que devuelven datos personales. Opciones: cerrarlas
fuera de `development` como tarjetas (`autorizacion_disponible` en `modules/tarjetas/router.py`),
o no pasar a `main` hasta tener F-03.

## cuentas

| # | Qué falta | Cómo resolverlo |
|---|---|---|
| 1 | **Crítico.** Un error de la BD devuelve al usuario el SQL y sus parámetros (`service.py:139-147`, usa `str(exc)`). | Agregar `ProblemDetailsRoute` al router, quitar el `try/except` y mover 52101-52105 a `_DB_ERRORES`. |
| 2 | Errores fuera del formato F-04 (`router.py:11`). | Mismo cambio del punto 1. |
| 3 | Cliente, producto y agencia inexistentes comparten code con "no activo" (`service.py:84-117`). | Separar `is None` del estado y crear `CLIENTE_NO_ENCONTRADO`, `PRODUCTO_NO_ENCONTRADO` y `AGENCIA_NO_ENCONTRADA` (422). Actualizar CTA-01. |
| 4 | `NumeroCuenta` con MAX + 1: dos aperturas simultáneas generan el mismo número y la segunda falla (`service.py:17-43`). | Usar una `SEQUENCE` en la BD, o reintentar ante 409 `REGISTRO_DUPLICADO` (ya lo traduce core con F-04). |
| 5 | No se audita la apertura. | `audit.registrar` en éxito y fallo, como tarjetas, salvo que el SP ya audite. |
| 6 | 2 pruebas de `tests/integration/test_cuentas_db.py` fallan contra la BD real. | Revisar si cambió el esquema o la prueba. |
| 7 | `_problema` propio (`service.py:64`). | Cambiar por `problema` de core. |

## clientes

| # | Qué falta | Cómo resolverlo |
|---|---|---|
| 1 | La IP del historial sale de `X-Forwarded-For`, que el usuario puede inventar (`router.py:244`). | Usar `ip_cliente(request.scope)`. |
| 2 | `_gestion_router` (validar identificación, registro, direcciones) no usa F-04: un error de BD da 500 en texto plano y deja datos del cliente en el log (`router.py:31`). | `APIRouter(route_class=ProblemDetailsRoute)` y `responses=RESPUESTAS_ERROR`. |
| 3 | Textos sin `max_length`: `nombres`, `apellidos`, `razon_social`, `calle_direccion`, `referencia_ubicacion` (`schemas.py`) y `q`, `identificacion` en CLI-03. | `max_length` igual al tamaño de la columna. |
| 4 | Errores de campo (`DOCUMENTO_INVALIDO`, `FECHA_NACIMIENTO_INVALIDA`, `TIPO_PERSONA_INVALIDO`, `CATALOGO_INVALIDO`) no indican el campo. | 400 con `errors[{field, message}]`; decidirlo con el frontend. |
| 5 | Cédula duplicada en registros simultáneos. | Ya responde 409 `REGISTRO_DUPLICADO` desde core, pero solo en routers con F-04: depende del punto 2. |
| 6 | Eliminar dirección no deja historial ni IP (`service.py:544`). | Insertar en `ClientesHis` como al agregar o editar. |
| 7 | `q` acepta `%` y `_` como comodines y fuerza un barrido de la tabla (`repository.py:410`). | Escaparlos y usar `LIKE ... ESCAPE`. |
| 8 | `_problema` propio (`service.py:42`). | Cambiar por `problema` de core. |

## contabilidad

| # | Qué falta | Cómo resolverlo |
|---|---|---|
| 1 | Errores fuera del formato F-04; el `TODO(F-04)` ya se puede cerrar (`router.py:11`, `service.py:19`). | Agregar `ProblemDetailsRoute` y `RESPUESTAS_ERROR` al router. |
| 2 | `_problema` propio (`service.py:22`). | Cambiar por `problema` de core. |

