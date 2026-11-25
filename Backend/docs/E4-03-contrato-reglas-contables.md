# Contrato para frontend · Reglas contables

`GET /api/v1/contabilidad/reglas-contables`. Requiere autenticación y la función `contabilidad.plantillas.consultar` cuando el control de funciones SQL está activo. La API conserva el permiso anterior en el modo de compatibilidad. No recibe cuerpo.

| Parámetro | Tipo | Comportamiento |
|---|---|---|
| `fecha` | Fecha ISO `YYYY-MM-DD`, opcional | Evalúa la selección del motor para ese día. Si se omite, usa la fecha del calendario contable. |
| `agencia` | Cadena de tres dígitos, opcional | Filtra Bóveda. El alcance predeterminado es la agencia de sesión, salvo acceso global administrativo. Las plantillas generales siguen incluidas. |

Respuesta 200 con `fechaContable` de tipo fecha o `null`, `matrizBovedaDisponible` booleana y `reglas` como arreglo. La consulta no pagina. Devuelve primero las versiones ordenadas por código y versión descendente y luego Bóveda por agencia, tipo y naturaleza. Una fecha no disponible devuelve `fechaContable: null` sin perder el inventario. Una matriz ausente o sin visibilidad devuelve `matrizBovedaDisponible: false`.

### Campos comunes

| Campo | Tipo y significado |
|---|---|
| `idRegla` | Cadena opaca y estable para la fila. |
| `fuente` | Discriminador `PLANTILLA_ASIENTO` o `PLANTILLA_BOVEDA`. |
| `versionada` | Booleano que indica si se administra mediante E4-03. |
| `Origen` | Módulo contable técnico. |
| `CodigoTipoAsiento` | Código o `null`. |
| `configurada` | `true` para cada fila devuelta. Indica presencia en el catálogo. |
| `desde`, `hacia` | Tipos de extremo operativo o `null` si no se conoce el flujo. |
| `consumidor` | Código del flujo identificado o `null`. |
| `integracion` | `CONECTADA` si existe un productor conectado en el backend, `PENDIENTE` si se conoce la familia pero falta conectar el flujo, `SIN_VERIFICAR` para el resto. |

### Variante versionada

`IdPlantillaAsiento`, `CodigoPlantilla`, `Version`, `Nombre`, `VigenciaDesde`, `VigenciaHasta`, `Estado`, `CodigoConcepto`, `Prioridad`, `vigente` y `Usada`. Los IDs y la versión son enteros. `Estado` y `Usada` son booleanos. Fecha final, concepto y prioridad admiten `null`. `vigente` es `true` para la versión seleccionada por el motor. `null` indica que falta una fecha de evaluación. `Prioridad` es el orden de las versiones elegibles de esa familia, comenzando en 1. `Usada` indica al menos un asiento vinculado, sin limitar a la fecha consultada.

`IdAgencia` es una cadena de tres dígitos para las familias BOV y `null` para las reglas generales. Si alguna etapa de traslado carece de versión seleccionable, ambas etapas usan la matriz anterior. La selección por fecha de cada fila informa elegibilidad de la versión y la evidencia efectiva de uso está en `Usada`.

Obtener las líneas con `GET /api/v1/contabilidad/plantillas/{IdPlantillaAsiento}`. Para escribir, usar los endpoints E4-03 con permiso de edición y el flujo E0-08. La elegibilidad del catálogo y la evidencia de uso son indicadores independientes.

### Variante Bóveda

`IdAgencia`, `TipoMovimiento`, `Naturaleza` (I/E), `EstadoTipo`, `EsManual`, `Debe`, `Haber`, `Habilitada`, `Version` y `vigente`. `Debe` y `Haber` traen códigos de cuenta o `null`. `EstadoTipo` y `EsManual` pueden ser nulos. `Habilitada` valida tipo automático activo y cuentas hoja activas e imputables. `Version` y `vigente` son siempre nulos. Presentar las cuentas directamente en el detalle de la fila y deshabilitar las acciones de edición, simulación y aprobación E4-03 para esta variante.

La API devuelve 400 por parámetros inválidos, 401 si falta autenticación y 403 si falta permiso o acceso a la agencia. El esquema de OpenAPI usa `fuente` como discriminador. Para renderizar estados, mantener separados el registro configurado, su selección por fecha y la integración.
