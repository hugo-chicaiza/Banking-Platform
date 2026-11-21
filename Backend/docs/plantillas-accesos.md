# Plantillas contables: consulta y edición independientes

Con `EDITOR_FUNCIONES_ACTIVO=true`, el editor administra estas funciones:

| Función | Operaciones | Roles iniciales |
|---|---|---|
| `contabilidad.plantillas.consultar` | GET listado de versiones y GET detalle | ADMIN, SUPERVISOR, AUDITOR, CONTADOR |
| `contabilidad.plantillas.editar` | POST simulación y POST creación de versión | CONTADOR, según la matriz previa del repositorio |

Las rutas son `/api/v1/contabilidad/tipos-asiento/{id_tipo}/plantillas` (GET/POST), `/api/v1/contabilidad/plantillas/{id_plantilla}` (GET) y `/api/v1/contabilidad/plantillas/simulaciones` (POST).

Edición requiere consulta. Se reutilizan `Seguridad.AccesoFuncionRol`, auditoría, versión de configuración y coordinación del guardado. Las entradas nuevas usan sus valores iniciales si no hay un ajuste guardado: no se reemplazan personalizaciones existentes ni se requiere una migración de Plantillas.

`require_auth` valida la función concreta por método y ruta; `require_permiso` reconoce esa autorización sin exigir además el permiso remoto equivalente. Retirar una función no puede eludirse conservando el antiguo permiso de WorkOS. La dependencia global `con-plantilla-editar` queda como respaldo compatible para cuando el editor está desactivado; en ese modo conserva el comportamiento previo, sin ampliar la consulta a los cuatro roles.

No se modifican asignaciones de WorkOS. Los roles iniciales proceden de la matriz del código, no de una lectura del tenant: si existen concesiones remotas adicionales de edición, deben revisarse antes del despliegue para decidir sus ajustes explícitos en el editor.

Crear sigue registrando una versión pendiente (`Estado=0`). No concede aprobación ni evita `AUTOAPROBACION_PROHIBIDA`; la activación de una versión conserva su recorrido independiente. Este ajuste no acredita que toda la integración preexistente de la cola de aprobación esté completada.

## Comprobaciones

- Los cuatro roles consultan sin obtener implícitamente edición; otros roles conservan la denegación inicial.
- CONTADOR conserva edición según la matriz vigente. Un ADMIN puede configurar edición por el mecanismo existente, pero ser ADMIN no la concede automáticamente.
- Las APIs validan cada función: 403 si falta acceso; una petición autorizada con cuerpo inválido sigue devolviendo el 400 de validación del proyecto.
- Dependencia de consulta, concesión/retiro, múltiples roles y compatibilidad con control desactivado se comprueban en las pruebas del editor y Plantillas.

No se agregan endpoints de aprobación, tablas ni columnas. Productos, E201 y las otras funciones se mantienen sin cambios.
