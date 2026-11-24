# E5-10 / #57 — tipos, permisos e histórico de direcciones

## Contrato y compatibilidad

- `GET /api/v1/catalogos/tipos-direccion`: catálogo para usuarios autenticados, igual que los demás catálogos de consulta compartida. Devuelve `[{codigo, nombre, estado}]`; estado `A` o `I`. Incluye retirados para identificar tipos usados anteriormente.
- El código es estable y se guarda en `Clientes.Direcciones.TipoDireccion`; el nombre es la etiqueta de presentación. No se cambia esa columna ni se reescriben las direcciones existentes. La estructura documental existente declara `varchar(20)`.
- Los cuatro tipos iniciales son Domicilio, Trabajo, Correspondencia y Otra. Se conservan además los valores que ya existan en las direcciones al migrar.
- Se reutiliza la administración general de catálogos para editar nombre/estado del tipo. No se añade una pantalla paralela ni un endpoint que elimine tipos usados. El alta de tipos por formulario no forma parte de #57.
- Backend consulta el catálogo al asignar tipo en registro o alta de dirección, o al cambiarlo. Un tipo inexistente, retirado o con código distinto responde 422 `TIPO_DIRECCION_INVALIDO`. Editar otra propiedad permite conservar un tipo que después se retiró.
- El formulario de gestión consume el catálogo, conserva el borrador durante carga/error/reintento y presenta el tipo previo retirado para no perder información. El registro inicial ampliado de #39 y sus otros catálogos no se implementan con este cambio.

## Permisos e histórico

- Se conservan `clientes.direcciones.consultar` y `clientes.direcciones.gestionar` del editor existente, sus dependencias y las restricciones operativas. No se crean roles o permisos nuevos en WorkOS.
- Sin consulta, se oculta la sección y el backend vacía `direcciones` en las respuestas generales de listado, ficha, perfil y mutaciones del cliente. El endpoint de direcciones conserva su autorización. No basta con ocultar botones.
- En mutaciones del cliente, la visibilidad se resuelve antes de guardar, evitando que una segunda consulta de permisos falle después de confirmar la operación.
- El control por funciones apagado conserva la respuesta backend anterior; no se activa ni cambia esa configuración con este desarrollo.
- La lista específica incluye Activo, Inactivo y Eliminado. La ficha muestra las no activas aparte y sin acciones. El estado Eliminado sigue siendo una baja lógica, no DELETE físico. Backend conserva sus reglas: impide editar Eliminado y promover una no activa; no se amplían aquí las operaciones sobre estados heredados.
- La baja e historial siguen en una transacción y no se duplica la auditoría en un reintento de retirada ya confirmada. El historial general conserva su permiso independiente.

## Despliegue posterior, no ejecutado

Orden: revisar/aplicar la migración `cooperativa/202611230900_tipos_direccion.up.sql`, desplegar backend y después frontend. El backend nuevo requiere la tabla del catálogo, también al registrar la dirección principal de C-01.

La migración reemplaza checks exclusivos de TipoDireccion por una FK al catálogo; rechaza checks combinados con otras columnas para no eliminarlos silenciosamente. Conserva filas y no modifica la auditoría. Revisar esquema/collation y permisos del destino antes de aplicarla fuera del laboratorio.

El script `.down.sql` restaura la restricción antigua solo si no existen direcciones con tipos nuevos. En caso contrario se niega a continuar para impedir pérdida de datos. No ejecutar una reversión de código o esquema sin revisar ese caso.

## Pruebas

- `tests/unit/test_direcciones_catalogo.py`: SQL SQLite aislado para catálogo y consulta de retiradas, tipos nuevos/inactivos, compatibilidad al editar y visibilidad de ficha/listado/perfil.
- `tests/unit/test_direcciones_persistencia.py`: relación entre cliente/dirección/historial, principal, campos omitidos frente a null, identidad generada, fallo de confirmación y baja lógica. Usa un cursor controlado para el contrato con el driver; no sustituye el ensayo T-SQL.
- `tests/unit/test_direcciones_http.py`: identidad del operador en alta/edición y comprobación de permisos antes de guardar. Preserva los contratos existentes del registro.
- Pruebas existentes de clientes, funciones, autorización e inventario de APIs se conservan y amplían con el endpoint nuevo.
- El laboratorio externo al repositorio `outputs/direcciones-57-demo` utiliza SQL LocalDB, la migración y los routers/servicios/repositorios de direcciones de este checkout. Identidad y datos generales del cliente son ficticios; no acredita WorkOS o SQL de Azure. Ensaya reversión e idempotencia en otra base local exclusiva.
