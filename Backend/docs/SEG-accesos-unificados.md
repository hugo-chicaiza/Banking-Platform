# Accesos de sección sobre la configuración integrada

Esta ampliación conserva los endpoints y el catálogo de permisos de WorkOS de SEG01..10, incluida la creación y eliminación integradas en #473. No crea permisos `acceso:*` ni otro almacenamiento de asignaciones.

## Configuración y compatibilidad

Se reutiliza `SeguridadDB.Seguridad.PestanaRol` y la migración `20261118_seguridad_pestana_rol.tsql` ya existente. Este cambio no aplica esa migración ni modifica el esquema. Debe verificarse su instalación antes de activar la política en un entorno real.

`EDITOR_ACCESOS_ACTIVO` es false por defecto. Desplegar código no lo activa. Con false, `/auth/me` conserva el contrato anterior y las APIs mantienen la autorización existente. Con true, se calculan las secciones efectivas de cada usuario desde SQL y se añade una restricción por sección a las operaciones clasificadas. Un fallo de lectura responde 503; no se utiliza la ausencia de tabla como autorización.

Los roles y permisos operativos de WorkOS, la pertenencia a la organización, el vínculo interno y la agencia siguen aplicándose. Habilitar una sección nunca sustituye sus controles de operación ni da acceso a otra agencia. Una personalización SQL incompatible heredada no amplía el acceso efectivo.

## Contrato administrativo

- SEG11: GET `/api/v1/seguridad/pestanas/configuracion`, ADMIN, `Cache-Control: no-store`. Devuelve `version`, `activa`, `pestanas` y el catálogo `secciones` con roles compatibles.
- SEG12: PUT a esa misma ruta, ADMIN. Recibe `{version, motivo, pestanas}`; la lista representa la configuración completa. Devuelve la configuración persistida, su versión, su activación y `estado: GUARDADO`.
- El motivo contiene 10 a 160 caracteres, en una sola línea. La versión es un hash del catálogo y de las filas actuales; una versión anterior responde 409. Las rutas desconocidas, roles incompatibles y duplicados se rechazan. Inicio y ambos accesos administrativos del editor son fijos.
- El PUT SEG08 anterior se conserva. Con la política activa también exige versión y motivo; un consumidor antiguo no puede evitar el control del nuevo editor. Con la política desactivada conserva su contrato visual anterior; todo escritor debe actualizarse antes de activar.

El guardado usa `sp_getapplock` con propietario Transaction, comprueba la versión y guarda configuración y auditoría en una única transacción SQL. Si falla la auditoría, se revierte el cambio. Si la respuesta se pierde o no se puede confirmar el resultado, el cliente conserva el borrador y debe releer antes de intentar otro guardado. El bloqueo no protege a escritores externos que ignoren este contrato.

No se elimina silenciosamente una fila de personalización cuyo identificador no esté reconocido en el catálogo. Las filas de rutas que no aparecen en la vista se conservan al enviar desde frontend.

## Aplicación de la política

`/auth/me` entrega `accesosSecciones: {version, habilitadas}` solo con activación explícita. `habilitadas` contiene rutas canónicas del catálogo, no URLs arbitrarias recibidas del navegador. Para varias funciones de usuario se combinan sus roles compatibles; quitar acceso a un rol no implica quitárselo a otro que también tenga asignado.

Frontend utiliza esa política en menú, rutas, subrutas y accesos rápidos. Actualiza su sesión después de guardar, limpia la caché si cambia la versión y avisa a las pestañas del mismo origen. Ofrece Actualizar accesos; no se añaden consultas periódicas que mantengan viva una sesión inactiva. No se garantiza una actualización visual inmediata en otros dispositivos.

Backend comprueba las rutas clasificadas en `core/security/secciones.py` antes de consultar datos de negocio. El resultado se reutiliza solo dentro de la petición. Una API nueva dentro de un ámbito administrado debe clasificarse; de lo contrario falla cerrado. Una prueba compara el mapa con OpenAPI.

Los selectores compartidos, plantillas, cortes y operaciones sin sección equivalente conservan sus reglas propias. ATM, Caja y Bóveda no se incorporan silenciosamente a este catálogo. Créditos permanece en preparación y su casilla solo afecta a esa pantalla sin APIs nuevas.

La búsqueda general de clientes también se utiliza desde Cuentas y Tarjetas: retirar Consulta de clientes bloquea esa misma API desde cualquier pantalla. Permitir un buscador limitado para otro flujo requeriría un contrato con campos y autorización propios, no una cabecera que diga desde qué pantalla se llama.

## Límites de esta entrega

No se incluyen excepciones por usuario, cola de aprobación ni notificaciones. ADMIN guarda directamente con motivo y auditoría; no se afirma que esto equivalga a doble revisión. Los cambios de permisos de WorkOS conservan el comportamiento y los tiempos de renovación del módulo integrado por el equipo.

Las pruebas de esta ampliación usan SQL y WorkOS simulados. Pendiente de autorización: comprobar la tabla y los permisos SQL de auditoría y bloqueo en el entorno elegido, y validar el flujo real antes de activarlo. No hubo cambios en WorkOS ni Azure durante la implementación local.
