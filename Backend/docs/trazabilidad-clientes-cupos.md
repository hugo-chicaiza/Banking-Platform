# Trazabilidad de direcciones y cupos

Cambio del 2026-11-09 correspondiente al punto 7 de la revisión. La investigación del proxy y la configuración de Azure siguen pendientes; no se modifican cabeceras confiables, FORWARDED_ALLOW_IPS, middleware ni el helper existente de IP.

## Baja de direcciones — CLI-12

- DELETE toma el usuario interno de la sesión mediante UsuarioAuditoria; no recibe el autor desde el cuerpo o la consulta.
- La baja lógica de Direcciones y el INSERT de ClientesHis se ejecutan en la misma transacción, bajo el bloqueo del cliente. Si falla cualquiera de las escrituras, se revierten ambas.
- El historial conserva TipoOperacion=D, CampoModificado=DIRECCION.estado, usuario, IP recibida por el mecanismo actual, fecha UTC y observaciones JSON versionadas. Estas últimas contienen el identificador de la dirección y los estados anterior/nuevo.
- Un reintento sobre una dirección ya Eliminado devuelve 204 sin inventar otro cambio ni una segunda baja en el historial.
- La dirección principal activa sigue protegida y el historial existente permanece inmutable. CLI-07 ya permite consultar los registros nuevos.
- La procedencia y confiabilidad de la IP queda sujeta a la revisión pendiente del proxy; este cambio no declara confiable X-Forwarded-For.

## Historial de cupos — CTA-08/09

Por instrucción del solicitante se revierte la ampliación de Canal.CuposModHis. Se retiran MaxTransaccionesDiaAnterior, MaxTransaccionesDiaNuevo, FechaVigenciaAnterior y FechaVigenciaNueva, y las referencias a ellas en SQL, respuesta y OpenAPI de CTA-09.

- CTA-08 conserva la configuración vigente de frecuencia y caducidad en CanalCupoClienteCustom; esas columnas originales no se eliminan.
- El historial vuelve a su contrato original: importes anteriores/nuevos, autor, fecha y vínculo al personalizado. La captura histórica de frecuencia y caducidad queda pendiente de aprobación del equipo.
- Las escrituras del cupo y su historial siguen siendo transaccionales; si no existía personalizado, los importes anteriores son null.
- Se mantienen el trigger de inmutabilidad, los roles, la paginación y el orden de CTA-09.

## Despliegue y comprobación

El script de ampliación se retiró para evitar que vuelva a agregar las columnas. [20261109_revertir_columnas_historial_cupos.sql](../migrations/20261109_revertir_columnas_historial_cupos.sql) elimina únicamente esas cuatro columnas, exige que estén vacías y revierte toda la operación si encuentra datos. No borra filas ni modifica las demás columnas o los triggers; se puede ejecutar nuevamente si ya se revirtieron.

La reversión se ejecutó en la base configurada de esta sesión. Se comprobó que las cuatro columnas ya no existen, que se conservan las filas y valores originales del historial y que el trigger de inmutabilidad permanece igual.

Pruebas incluidas: autor real de la sesión, registros de baja y reintentos, rollback por fallo de historial/commit y funcionamiento de CTA-08/09 con el esquema original. Las pruebas contra SQL Server usan transacciones externas con rollback para no conservar escrituras de prueba.
