# Entidad de la organización

## Endpoints y permisos

La entidad representa a la cooperativa y corresponde a la fila con
`IdEntidad = 1` en `Organizacion.Entidad`, dentro de CooperativaDB.

| Método | Ruta | Roles | Respuesta exitosa |
| --- | --- | --- | --- |
| GET | `/api/v1/organizacion/entidad` | `ASESOR`, `ADMIN` | 200 con la entidad completa |
| PUT | `/api/v1/organizacion/entidad` | `ADMIN` | 201 con la entidad creada |
| PATCH | `/api/v1/organizacion/entidad` | `ADMIN` | 200 con la entidad completa después de editar |

Todas las operaciones requieren la sesión existente del backend. La autenticación,
el control de origen de las escrituras, los límites de peticiones y el formato
de errores utilizan los mecanismos compartidos del proyecto.

La clave primaria y `CK_Entidad_UnaFila` permiten como máximo una entidad.
Cuando la tabla está vacía, GET y PATCH responden
`404 ENTIDAD_NO_ENCONTRADA`. Un administrador puede crear el registro inicial
mediante PUT.

El GET también devuelve la entidad cuando su estado es `I`.

## Creación mediante PUT

`PUT /api/v1/organizacion/entidad` requiere exclusivamente el rol `ADMIN`.
Crea la fila con `IdEntidad = 1` y devuelve `201` con los 16 campos persistidos.
El cuerpo mínimo contiene los siguientes datos ficticios.

```json
{
  "ruc": "1790000000001",
  "razonSocial": "Cooperativa de prueba",
  "fechaConstitucion": "2000-01-01",
  "representanteLegal": "Representante de prueba",
  "identificacionRepresentante": "AB12345"
}
```

Los cinco campos del ejemplo son obligatorios y se validan con las mismas
restricciones del PATCH. También se pueden enviar los demás campos de negocio
descritos en la tabla de campos editables.

| Campo omitido | Valor al crear |
| --- | --- |
| `tipoOrganizacion` | `Cooperativa de Ahorro y Credito` |
| `estado` | `A` |
| `nombreComercial`, `segmento`, `numeroResolucionSeps`, `telefono`, `email`, `sitioWeb` | `NULL` |

El backend fija `idEntidad` en `1` y obtiene `modificadoPor` de la sesión del
administrador mediante `UsuarioAuditoria`. SQL Server asigna `fechaRegistro`
con el DEFAULT de la tabla en hora de Ecuador. Enviar estos tres campos en el
cuerpo produce `400 DATOS_INVALIDOS`.

Si la fila ya existe, PUT responde `409 ENTIDAD_YA_EXISTE`, incluso cuando se
repite el mismo cuerpo. La edición del registro existente se realiza mediante
PATCH. Dos PUT simultáneos se serializan mediante un bloqueo de rango sobre
la clave `1`, incluyendo el caso en que la tabla está vacía. Una solicitud crea
el registro y la otra recibe el conflicto al comprobar que ya existe.

## Consulta

Una respuesta de ejemplo con datos ficticios es la siguiente.

```json
{
  "idEntidad": 1,
  "ruc": "1790000000001",
  "razonSocial": "Cooperativa de prueba",
  "nombreComercial": "Cooperativa Ejemplo",
  "tipoOrganizacion": "Cooperativa de Ahorro y Credito",
  "segmento": 2,
  "numeroResolucionSeps": "SEPS-PRUEBA",
  "fechaConstitucion": "2000-01-01",
  "representanteLegal": "Representante de prueba",
  "identificacionRepresentante": "AB12345",
  "telefono": "022345678",
  "email": "entidad@example.com",
  "sitioWeb": "https://example.com",
  "estado": "A",
  "fechaRegistro": "2026-11-11T20:15:41",
  "modificadoPor": 1
}
```

Los nombres JSON siguen el `camelCase` de `CamelModel`. En particular, la columna
`NumeroResolucionSEPS` se representa como `numeroResolucionSeps`.

## Edición parcial

El cuerpo debe contener al menos un campo editable. Por ejemplo, este PATCH
actualiza el nombre comercial y vacía el teléfono.

```json
{
  "nombreComercial": "Cooperativa Ejemplo",
  "telefono": null
}
```

| Forma de envío | Efecto |
| --- | --- |
| Campo omitido | Conserva su valor persistido |
| Campo enviado con un valor válido | Actualiza ese campo |
| Campo anulable enviado con `null` | Guarda `NULL` |
| Campo obligatorio enviado con `null` | Responde 400 `DATOS_INVALIDOS` |
| Cuerpo vacío `{}` o campo desconocido | Responde 400 `DATOS_INVALIDOS` |
| Todos los valores enviados coinciden con los actuales | Devuelve 200 con los datos actuales |

Los campos `idEntidad`, `fechaRegistro` y `modificadoPor` son administrados por
el backend. Enviarlos en PUT o PATCH produce `400 DATOS_INVALIDOS`.
`ModificadoPor` se obtiene del identificador interno del usuario autenticado
mediante `UsuarioAuditoria` y se actualiza cuando hay cambios efectivos.
Repetir los valores actuales conserva el autor de la última modificación.

### Campos editables

Todos los campos de esta tabla son opcionales en el cuerpo del PATCH.
La columna «Admite null» indica si se puede vaciar su valor explícitamente.

| Campo JSON | Admite null | Validación |
| --- | --- | --- |
| `ruc` | No | Exactamente 13 dígitos ASCII, terminado en `001` |
| `razonSocial` | No | Entre 1 y 250 caracteres, con algún carácter distinto de espacios |
| `nombreComercial` | Sí | Hasta 150 caracteres |
| `tipoOrganizacion` | No | Entre 1 y 60 caracteres, con algún carácter distinto de espacios |
| `segmento` | Sí | Entero de 1 a 5 |
| `numeroResolucionSeps` | Sí | Hasta 60 caracteres |
| `fechaConstitucion` | No | Fecha válida, por ejemplo `2000-01-01` |
| `representanteLegal` | No | Entre 1 y 250 caracteres, con algún carácter distinto de espacios |
| `identificacionRepresentante` | No | De 5 a 13 caracteres, exclusivamente `0-9` y `A-Z` |
| `telefono` | Sí | Hasta 15 caracteres |
| `email` | Sí | Hasta 150 caracteres |
| `sitioWeb` | Sí | Hasta 150 caracteres |
| `estado` | No | `A` o `I` |

El contrato valida el formato de RUC definido por el DDL proporcionado.
Las validaciones de teléfono, email y sitio web corresponden a las longitudes
de sus columnas. Los textos opcionales también admiten una cadena vacía.
El estado permite los cambios `A` → `I` e `I` → `A`.

PUT y PATCH aceptan sus datos en el cuerpo de la solicitud. Cualquier parámetro
de consulta en GET, PUT o PATCH produce `400 PARAMETRO_INVALIDO`.

## Transacción y auditoría

La creación abre una transacción, verifica la ausencia de la entidad con
`UPDLOCK, HOLDLOCK`, inserta la fila y lee su representación persistida antes
del commit. Un fallo durante la operación revierte la creación completa.
Después del commit registra `CREAR_ENTIDAD` sobre `Organizacion.Entidad`
mediante el mecanismo best-effort existente. El evento contiene el identificador
del registro, usuario e IP. Los conflictos de creación devuelven 409.

La edición abre una transacción, obtiene la entidad con `UPDLOCK, HOLDLOCK`,
compara los valores enviados y actualiza únicamente los campos que cambiaron.
El bloqueo se mantiene hasta el commit o rollback. La respuesta se construye
leyendo los datos persistidos dentro de esa misma transacción.

Las ediciones concurrentes se aplican en orden de adquisición del bloqueo.
Cada PATCH conserva los campos que omitió. Cuando dos solicitudes cambian
el mismo campo, prevalece el último valor aplicado.

Los cambios efectivos registran `EDITAR_ENTIDAD` sobre `Organizacion.Entidad`
mediante la auditoría best-effort existente, después del commit. El evento
incluye el identificador del registro, usuario, IP y nombres de campos
modificados. Los valores de los campos permanecen en la tabla de entidad.
Una repetición de valores actuales devuelve 200 y omite la escritura de
auditoría de cambio. Si falla la operación SQL, la transacción hace rollback.

## Errores

Las respuestas usan `application/problem+json` con `type`, `title`, `status`,
`code`, `detail` y `traceId`. Los errores de validación agregan `errors` con
el campo y el motivo.

| HTTP | Código | Causa |
| --- | --- | --- |
| 400 | `DATOS_INVALIDOS` | Cuerpo inválido, vacío, campos adicionales o valores fuera del contrato |
| 400 | `PARAMETRO_INVALIDO` | Parámetros de consulta desconocidos o repetidos |
| 401 | `NO_AUTENTICADO` | Sesión ausente o inválida |
| 403 | `SIN_PERMISO` | El usuario carece de un rol permitido |
| 403 | `USUARIO_NO_REGISTRADO` | El usuario carece de un registro interno activo |
| 403 | `USUARIO_SIN_VINCULO_AUDITORIA` | Falta el vínculo interno requerido por `UsuarioAuditoria` |
| 403 | `ORIGEN_NO_PERMITIDO` | El origen de la escritura incumple la validación existente |
| 404 | `ENTIDAD_NO_ENCONTRADA` | Falta la fila con `IdEntidad = 1` |
| 409 | `ENTIDAD_YA_EXISTE` | El PUT encuentra la entidad ya registrada |
| 500 | `ERROR_INTERNO` | Fallo inesperado de persistencia o del servidor |

También se aplican las respuestas de autenticación, límites y traducción SQL
definidas por los componentes compartidos del backend.

## Pruebas en Swagger

1. Ejecutar el backend en un entorno con documentación habilitada.
2. Iniciar sesión mediante el flujo existente y abrir `/api/docs` en el dominio
   que utiliza esa sesión.
3. Buscar la etiqueta **Organización**. Aparecen **Crear la entidad**,
   **Obtener la entidad** y **Editar parcialmente la entidad**, con sus modelos,
   ejemplos y errores.
4. Si la tabla está vacía, con `ADMIN` ejecutar el PUT con el cuerpo mínimo de
   creación. Comprobar la respuesta 201 y que repetirlo devuelve 409.
5. Ejecutar el GET con un usuario `ASESOR` o `ADMIN`.
6. Con `ADMIN`, ejecutar el PATCH usando el cuerpo de ejemplo y consultar
   nuevamente el GET para comprobar el resultado.
7. Con `ASESOR`, comprobar que PUT y PATCH responden `403 SIN_PERMISO`.

La configuración de `app/main.py` habilita `/api/docs` y `/api/openapi.json`
cuando `APP_ENV` tiene un valor distinto de `production`.

## Pruebas automatizadas

`tests/unit/test_entidad.py` cubre el contrato HTTP, roles, creación inicial,
defaults, campos obligatorios, creación repetida, registro ausente,
edición parcial, null, longitudes, formatos, repetición, fallos de escritura
y commit, auditoría y documentación OpenAPI. Las rutas también están
registradas en `tests/unit/test_autorizacion.py`.

Desde la raíz del repositorio, en PowerShell, ejecutar las pruebas relacionadas.

```powershell
Backend/.venv/Scripts/python.exe -m pytest Backend/tests/unit/test_entidad.py Backend/tests/unit/test_agencias_estado.py Backend/tests/unit/test_autorizacion.py -q
```

`tests/integration/test_entidad_sql_lab.py` ejecuta los endpoints y servicios
contra SQL Server real. Crea una base local temporal `Entidad_Test_<uuid>`
con el DDL proporcionado y datos ficticios. Al finalizar cierra las conexiones
de esa base y la elimina. Usa autenticación integrada de Windows y requiere
permisos para crear bases y ODBC Driver 18 for SQL Server.

La instancia predeterminada es `.\SQLEXPRESS`. `ENTIDAD_LOCAL_SQL_SERVER`
permite seleccionar otra instancia del mismo equipo. La activación explícita
de estas pruebas se realiza mediante una variable de entorno.

```powershell
$env:ENTIDAD_LOCAL_SQL_ENABLED = "1"
$env:ENTIDAD_LOCAL_SQL_SERVER = ".\SQLEXPRESS"
try {
    Backend/.venv/Scripts/python.exe -m pytest Backend/tests/integration/test_entidad_sql_lab.py -q
} finally {
    Remove-Item Env:ENTIDAD_LOCAL_SQL_ENABLED
    Remove-Item Env:ENTIDAD_LOCAL_SQL_SERVER
}
```

La suite comprueba creación con defaults y fecha asignada por SQL Server,
alta con todos los campos, creaciones repetidas y simultáneas, bloqueo de rango
sobre la tabla vacía, rollback de la inserción, GET con ambos roles y
persistencia de todos los campos,
null frente a omisión, `NOCOUNT ON/OFF`, repetición, entidad ausente,
rollback después de un error SQL, bloqueo entre dos conexiones, reintento
y restricción de una sola entidad. Las sesiones HTTP y la persistencia
de auditoría se simulan con los mecanismos de prueba existentes del proyecto.
