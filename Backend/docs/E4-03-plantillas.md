# E4-03 Administrar plantillas

Esta rama depende del código y de las migraciones E4-01.

- `GET /contabilidad/tipos-asiento/{id}/plantillas` lista versiones.
- `GET /contabilidad/plantillas/{id}` incluye el detalle.
- `POST /contabilidad/tipos-asiento/{id}/plantillas` guarda una nueva versión
  pendiente y devuelve 202. Requiere una plantilla base única para el tipo.
- `POST /contabilidad/plantillas/simulaciones` recibe líneas, montos de
  ejemplo y un mapa de cuentas para los roles en prueba. Devuelve las líneas
  y el total de débitos usando el mismo resolvedor del motor.

Las rutas usan el permiso WorkOS `con-plantilla-editar`. El manejador
interno `confirmar_aprobacion` exige una transacción, una segunda identidad
y una vigencia futura. Al activarse, delimita el fin de vigencia de la
versión anterior. Los disparadores de E4-01 protegen el detalle registrado.

La creacion devuelve 202 con `idPlantillaAsiento` e `idSolicitud`.
La cola E0-08 resuelve `CON-PLANTILLA` con sus endpoints de aprobar y rechazar.
El solicitante requiere CONTADOR y `con-plantilla-editar`. El aprobador requiere
el permiso efectivo `con-plantilla-aprobar` en WorkOS y debe ser otra persona.
Al ejecutar se registra `CON_PLANTILLA_PROGRAMADA`. Una solicitud rechazada
conserva la version inactiva y el resultado historico en E0-08. Cree una nueva
version para presentar una propuesta distinta.

La version y la solicitud se guardan en bases diferentes. Si falla la cola
despues de guardar la version, el creador puede listar las versiones y enviar
esa version con `POST /contabilidad/plantillas/{id_plantilla}/solicitudes`.
El envio no vuelve a crear la version y se admite una sola solicitud por
version, incluso cuando ya fue resuelta. El motor nunca usa versiones inactivas.

Instalar primero E4-01 y los catalogos de aprobaciones y auditoria. Luego
aplicar `202611191500_plantillas_aprobacion.up.sql` en SeguridadDB con
`migration_database` configurado. La asignacion efectiva de WorkOS se verifica
en el entorno antes de habilitar el flujo. Falta definir la cobertura exigida
por producto o subproducto para cada familia.

Prueba local: con PYTHONPATH apuntando a Backend, ejecute
tests/integration/e403_sql_lab.py con la base local ya preparada por el
ensayo de E4-01. Los IDs de usuario del ensayo son datos del laboratorio.

Cuando un tipo tenga varias familias, indique codigoPlantilla al crear su
versión. El GET del tipo devuelve este código para seleccionar la familia.

## Contrato para la pantalla de plantillas

Todas las rutas siguientes usan el prefijo `/api/v1`. Las lecturas de plantillas
usan `contabilidad.plantillas.consultar` con el editor de funciones activo y
`con-plantilla-editar` con el editor apagado. Las escrituras usan la función
`contabilidad.plantillas.editar` o el permiso WorkOS anterior. E0-08 comprueba
los permisos efectivos del solicitante y aprobador al ejecutar acciones.

| Método y ruta | Contrato |
| --- | --- |
| `GET /contabilidad/plantillas` | Array de versiones. Filtros opcionales `q` (fragmento literal de nombre o código), `codigo` (familia), `estado` (0 o 1), `origen` e `idTipoAsiento`. Se combinan entre sí |
| `GET /contabilidad/tipos-asiento/{id_tipo}/plantillas` | El mismo resumen para un tipo. Para el historial de una familia usar el listado global con `codigo` y, si corresponde, `idTipoAsiento`, sin filtro de estado |
| `GET /contabilidad/plantillas/catalogos` | Objeto con `tiposAsiento` y `conceptosContables`. Los tipos incluyen `IdTipoAsiento`, `Codigo`, `Nombre`, `Descripcion`, `EsManual` y `Estado`. Los conceptos incluyen `IdConceptoContable`, `CodigoConcepto`, `ConceptoDetalle` y `Estado` |
| `GET /contabilidad/cuentas-contables?imputable=true&q=texto` | CON-03 existente, con su permiso de lectura. Para elegir una cuenta fija, mostrar únicamente auxiliares de 8 dígitos con `estado: "Activo"` y usar `idCuentaContable` como valor |
| `GET /contabilidad/plantillas/{id_plantilla}` | Cabecera, tipo, concepto y `lineas` ordenadas. Cada línea incluye `Orden`, `IdCuentaContable`, `CodigoCuenta`, `NombreCuenta`, `TipoMovimiento`, `ComponenteImporte`, `OrigenCuenta` y `CodigoRol`. Las cuentas dinámicas se resuelven con el contexto y pueden devolver campos de cuenta nulos |
| `POST /contabilidad/tipos-asiento/{id_tipo}/plantillas` | Crea y envía una nueva versión de una familia existente. Recibe `codigoPlantilla`, `nombre`, `vigenciaDesde` (fecha ISO) y `lineas`. Cada línea recibe `lado`, `origen`, `base` y, según su origen, `cuenta` o `rol`. Devuelve 202 con `idPlantillaAsiento` e `idSolicitud` |
| `POST /contabilidad/plantillas/simulaciones` | Valida y simula `lineas` con `montos` por componente y, cuando correspondan, mapas `producto` y `contraproducto` por rol y la cuenta `comision`. Devuelve `lineas` y `total` |
| `GET /contabilidad/plantillas/{id_plantilla}/solicitudes` | Devuelve el resumen E0-08 visible para el usuario, con `idSolicitud`, `estado`, `puedeAprobar`, `puedeRechazar` y `puedeCancelar`. Devuelve `null` cuando no hay una solicitud visible |
| `POST /contabilidad/plantillas/{id_plantilla}/solicitudes` | Reintenta el envío de la versión existente si la versión se guardó y la solicitud no llegó a crearse. Se mantienen las validaciones de E0-08 |
| `GET /aprobaciones/{idSolicitud}` y `POST /aprobaciones/{idSolicitud}/{acción}` | Ficha con eventos y resolución en la cola existente. Acciones `aprobar`, `rechazar` y `cancelar`. Para rechazar, enviar `comentario` obligatorio |

El resumen de versión contiene `IdPlantillaAsiento`, `CodigoPlantilla`, `Nombre`,
`Version`, `Estado`, `Origen`, `VigenciaDesde`, `VigenciaHasta`,
`CreadoPor`, `AprobadoPor`, `FechaAprobacion`, los IDs de tipo y concepto y sus
etiquetas `CodigoTipoAsiento`, `NombreTipoAsiento`, `CodigoConcepto` y
`ConceptoDetalle`. Se ordena por familia y versión descendente. `Estado` es el
bit contable, que se serializa como booleano. Para distinguir programada,
vigente e histórica, combinarlo con las fechas y la fecha contable de
`GET /contabilidad/fechas-contables/actual`. Para distinguir pendiente,
rechazada y ejecutada, usar el estado E0-08. El acceso a una plantilla no
concede acceso a la solicitud de otra persona.

La edición crea una versión. La API conserva origen, tipo y concepto de la
familia base. Los catálogos permiten seleccionar filtros y mostrar esos
valores, que son de solo lectura en el formulario de edición.

Los errores usan `application/problem+json`. Mostrar `detail` y usar `code`
para decidir la acción. Un ID mal formado o fuera del rango devuelve
`400 DATOS_INVALIDOS`. `errors[].field` identifica el campo y algunos mensajes
de validación de esquema provienen de Pydantic. La interfaz puede traducir esos
mensajes con el nombre del campo. La falta de permisos devuelve 403. Una
plantilla inexistente devuelve `404 PLANTILLA_NO_DEFINIDA` en detalle. Entre los
errores de escritura están `409 TIPO_AMBIGUO`, `409 VIGENCIA_INVALIDA` y
`422 PLANTILLA_NO_CUADRA`, `CUENTA_CONTABLE_NO_HABILITADA`, `ROL_NO_DEFINIDO`
u `ORIGEN_INVALIDO`.
