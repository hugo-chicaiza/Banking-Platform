# Editor de funciones por rol

## Propósito y alcance

WorkOS autentica y entrega los roles; Enquo guarda qué funciones concede o retira de cada rol. En las 87 operaciones HTTP explícitamente clasificadas, una autorización SQL sustituye el control estático equivalente de rol/permiso remoto. No se actualizan roles ni permisos en WorkOS.

El catálogo `funciones_catalogo.py` contiene 51 funciones separando consulta, registro, edición, estado, historial, PIN e importaciones. Los valores iniciales se contrastan mediante una prueba con la matriz de autorización existente del equipo; no son una copia de las asignaciones reales del tenant WorkOS.

La sincronización incorpora los alias administrativos `/api/v1/organizacion/agencias` del equipo a las mismas funciones de Agencias que sus rutas anteriores. Ambos nombres de ruta aplican la misma decisión SQL; no se añade una vía alternativa para saltarse una retirada. Se mantienen las versiones y el flujo de aprobación del mantenimiento de agencias.

La administración de usuarios/roles/agencias de usuarios permanece protegida para ADMIN, no delegable. Consultar usuarios sí es una función delegable. Los endpoints del editor, permisos de WorkOS, autenticación y contexto de agencia mantienen sus protecciones administrativas/operativas previas.

Fuera del catálogo (ATM, Caja, Bóveda, mantenimiento de Parámetros, plantillas, reclasificaciones y otras excepciones) se conservan las reglas anteriores. Parámetros E1-10 está declarado explícitamente en `SECCIONES_LEGADAS`: conserva su control de sección y sus validaciones operativas y de aprobación. No se añade al editor de funciones ni se sustituyen sus permisos. No se cambia el comportamiento global de cualquier `require_roles`: la sustitución exige coincidencia exacta de método y patrón de ruta. Los selectores compartidos mantienen autenticación y restricciones previas. Un nuevo endpoint dentro del ámbito administrado, sin clasificación ni excepción explícita, falla cerrado.

Persisten la identidad interna activa, validación de sesión/origen, organización, agencia, alcance de registros, estados de negocio, validaciones, límites, idempotencia y seguridad del PIN. Por ejemplo, poder cambiar el estado de un cliente no permite una transición inválida ni omitir la comprobación de productos asociados.

## Contrato

### SEG13 — GET /api/v1/seguridad/accesos/configuracion

Solo ADMIN; `Cache-Control: no-store`. Devuelve `version`, `activa`, `modelo: FUNCIONES_POR_ROL`, los roles conocidos, `funciones` y `ajustes`. Cada función describe id, nombre, módulo, rutas frontend, rolesIniciales, dependencias, delegable y motivoProteccion.

No devuelve operaciones o rutas elegidas por el cliente: el catálogo se controla en código. Las APIs nuevas requieren clasificación y pruebas. Esta consulta no activa nada ni llama a WorkOS para asignar permisos.

### SEG14 — PATCH /api/v1/seguridad/accesos/configuracion

Solo ADMIN con vínculo interno válido. Ejemplo de concesión:

```json
{
  "version": "hash-de-64-caracteres-obtenido-en-la-consulta",
  "motivo": "Autorizar al supervisor para registrar clientes",
  "cambios": [
    {"funcion": "clientes.registrar", "rol": "SUPERVISOR", "permitido": true}
  ]
}
```

El ejemplo usa un marcador de versión; en una petición real se envía el hash hexadecimal recibido. `permitido: false` retira; `null` elimina el ajuste y devuelve el valor inicial. Una misma función/rol no puede repetirse. Máximo400 cambios, motivo de10..160 caracteres sin saltos de línea. El rol debe ser uno de los siete existentes en el código. No permite crear roles ni modificar funciones protegidas.

Un ajuste explícito igual al valor inicial sigue siendo una decisión explícita y puede auditarse como paso de herencia a ajuste. Repetir un ajuste que ya está exactamente guardado devuelve `cambiosAplicados: 0` sin nueva auditoría. El recuento describe ajustes cambiados, no usuarios afectados. Un PATCH modifica únicamente las parejas enviadas; no reemplaza toda la matriz.

Respuesta200: configuración canónica del estado que guardó esa transacción, más `estado: GUARDADO` y `cambiosAplicados`. `activa` no se cambia con el PATCH. No se hace una relectura fuera de la transacción que pueda devolver accidentalmente el guardado posterior de otra persona.

Errores:400 para forma/tipos/longitudes inválidos conforme al manejador común;401 sin sesión;403 sin ADMIN/vínculo;409 para versión anterior o bloqueo ocupado;422 para función desconocida, duplicada, protegida o dependencia incompleta;503 por fallo SQL/coordinación o resultado no confirmado. Los datos del error no incluyen credenciales.

La versión incluye catálogo, activación y ajustes completos. Un conflicto no escribe nada. El frontend futuro debe conservar base y borrador y comparar con una nueva consulta antes de confirmar otro envío; no basta con sustituir la versión de un borrador antiguo. No se implementa fusión automática de interfaz en este backend.

### AUT04 — GET /api/v1/auth/me

Con `EDITOR_FUNCIONES_ACTIVO=true`, añade `autorizacion: {version, activa: true, funciones, rutas}`. Roles y permisos WorkOS originales se devuelven sin modificarlos. El frontend futuro debe usar funciones como autoridad para las operaciones migradas y no volver a intersectarlas con las listas estáticas equivalentes.

Con el modelo apagado, no se añade `autorizacion` y continúa la conducta anterior. Con el nuevo modelo activo no se aplica además la política vieja de secciones. Una función retirada de un rol puede seguir disponible si otro rol de la persona la concede. Las dependencias incompletas no habilitan operaciones.

`rutas` indica las pantallas relacionadas con al menos una función efectiva, no concede por sí sola todas las acciones de esa pantalla. El frontend debe comprobar las funciones necesarias para cada vista/botón. Inicio y las pantallas administrativas del editor permanecen accesibles para ADMIN.

## SQL, auditoría y concurrencia

Migración nueva: `migrations/20261118_seguridad_acceso_funcion_rol.tsql`, para SeguridadDB. Tabla `Seguridad.AccesoFuncionRol`: Funcion varchar80, Rol varchar32, Permitido bit, ModificadoPor int con FK a Organizacion.Usuarios y FechaModificacion UTC. PK Funcion/Rol; checks de formato y roles. Las funciones conocidas se validan también en backend, no mediante una FK a un catálogo inexistente.

Guarda bajo `sys.sp_getapplock`, recurso `enquo-funciones`, propietario Transaction y timeout0. Revisa versión dentro del bloqueo. Ajustes y `Auditoria.Auditoria` pertenecen a la misma transacción. Fallar auditoría revierte todos los ajustes del PATCH.

Auditoría `CONFIGURAR_FUNCION`, tabla `Seguridad.AccesoFuncionRol`. `IDRegistro` es un SHA256 de la pareja función/rol (64 caracteres, respeta el límite100 existente); descripción legible incluye función, rol, ajuste anterior/nuevo y motivo. Sus longitudes de entrada caben en los500 caracteres existentes sin truncar el motivo. Un hash identifica el registro; no se usa para autenticar ni ocultar datos.

Nuevos permisos SQL necesarios para la identidad de despliegue: SELECT/INSERT/DELETE sobre la tabla nueva, SELECT sobre PestanaRol para comprobar transición, INSERT en auditoría y ejecución de bloqueo transaccional. No se amplían permisos SQL automáticamente ni se requiere ejecutar estos scripts en Azure para desarrollar localmente.

## Transición y reversión

`EDITOR_FUNCIONES_ACTIVO=false` por defecto, independiente del flag anterior `EDITOR_ACCESOS_ACTIVO`. Guardar no lo activa. Con el modelo nuevo activo sus APIs clasificadas se autorizan por funciones; el resto conserva controles previos. No activar antes de integrar el frontend que comprende este contrato.

No se convierten personalizaciones de `PestanaRol` en permisos de escritura. Si existen filas del editor anterior al activar, la lectura de autorización falla503 `MIGRACION_PESTANAS_PENDIENTE`; deben revisarse y migrarse explícitamente antes. No se borran ni se ignoran silenciosamente. El escritor antiguo responde409 `EDITOR_ANTERIOR_SOLO_LECTURA` cuando el modelo nuevo está activo.

Primero aplicar la migración en el entorno autorizado y comprobar defaults/asignaciones. Cargar ajustes no implica activarlos. Antes de una activación compartida revisar consumidores, reglas nuevas y permisos de la identidad efectiva. El frontend compañero está adaptado y validado en local: consume este contrato, usa `/auth/me.autorizacion` para menú, rutas y acciones, y conserva borradores ante errores y concurrencia. Esa validación usa identidad simulada y SQL local; no demuestra todavía el login con WorkOS real del nuevo modelo ni autoriza su activación compartida.

Reversión operativa: apagar el modelo y actualizar sesiones para recuperar reglas anteriores, conservando datos/auditoría. La reversión SQL manual `.down.tsql` se niega a borrar ajustes no vacíos y nunca elimina auditoría ni PestanaRol. Exportar/revisar ajustes antes de una reversión real. No ejecutar automáticamente en arranque.

## Verificación

- Unitarias: catálogo y valores iniciales; concesión/retirada; varios roles; lectura no concede edición; roles y permisos WorkOS equivalentes; contrato protegido; modelo apagado y dependencias.
- Prueba de inventario: todas las operaciones del editor anterior tienen exactamente una función y existen en OpenAPI.
- SQL local opt-in: persistencia, auditoría, no-op, PATCH independiente, versión anterior, bloqueo y carrera200/409, rollback de auditoría, motivo máximo, FK/checks, migración reejecutable, reversión y transición de pestañas.
- Prueba HTTP del router real de Clientes con política SQL local: concesión permite alcanzar registro201; retirada403. Se simula el guardado del cliente para no fabricar ni requerir el esquema de negocio completo. Identidad WorkOS simulada; sin llamadas al proveedor.
- Concurrencia manual desde el frontend: A retira el registro de Supervisor; B conserva un borrador de edición, incorpora el cambio de A y guarda únicamente su modificación. SQL conserva ambos resultados y los eventos #117/#118. La restauración posterior conserva la auditoría y registra dos eventos, uno por función (#119/#120). Estos identificadores corresponden exclusivamente al laboratorio local.

Las pruebas SQL se omiten normalmente y solo corren con `ENQUO_FUNCIONES_SQL_LAB=1`, instancia `(localdb)\EnquoAccesosQA`, SeguridadDB y marcador de laboratorio verificado. Nunca aceptan Azure como destino. No se afirma validación de guardados de clientes reales ni login WorkOS real de esta entrega.
