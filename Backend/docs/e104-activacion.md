# Activación de E1-04

La política se valida mediante `app.modules.auth.politica_roles.vigente()`. Antes de desplegar, compruebe con la configuración de destino que la validación pasa. `E104_POLITICA_ROLES` es un objeto JSON con `niveles` para los siete perfiles reconocidos, `privilegiados` e `incompatibles`. Estas dos listas pueden estar vacías si la política institucional lo establece. Las incompatibilidades configuradas se aplican a todo el conjunto de roles del usuario.

Las consultas y la edición de perfil, agencia y estado siguen disponibles en ausencia de la política. Las altas que asignan un rol y las sustituciones efectivas de roles requieren la política. La comprobación previa al despliegue evita descubrir esta restricción durante un alta.

Para habilitar la cola, aplique `202611240900_e104_roles_aprobacion.up.sql` mediante la conexión de migración de SeguridadDB. El contexto de sesión `migration_database` confirma el destino y `e104_permiso_aprobar_roles` recibe el permiso institucional global. Configure el mismo valor en `E104_PERMISO_APROBAR_ROLES`. El solicitante debe tener administración institucional vigente. El aprobador debe ser otra persona, distinta también del usuario objetivo, con el permiso efectivo. El cliente de roles debe aceptar `202` con una solicitud pendiente.

Para habilitar el diario de correo, aplique `202611240901_e104_recuperacion_correo.up.sql` en SeguridadDB, confirme que `APR_RECUPERACION` se ejecuta y habilite `E104_RECUPERAR_CORREO`. El flujo cubre el correo de una cuenta ya vinculada. En ese modo el correo se envía en una solicitud separada. La cola recupera el resultado tomando como destino el correo confirmado en SQL y comprobando la respuesta vigente de WorkOS.

Antes de habilitar el diario, aplique también `202611240902_e104_conciliacion_roles_invitacion.up.sql`. La misma tarea recupera roles directos de membresías ya vinculadas. Si una edición deja una invitación en estado ambiguo, conserva el trabajo pendiente y suspende el vínculo hasta verificar la invitación. Consulte el [contrato de frontend](e104-contrato-frontend.md).

Antes de retirar las opciones de recuperación o revertir el despliegue, confirme que la cola de roles y el diario de correo se han conciliado. Una solicitud de roles que queda en estado `Aprobada` requiere revisar su evidencia y el estado de WorkOS si el aprobador perdió el permiso o el objetivo cambió.

Mantenga `E104_CORTE_ASIGNACION_CAJA` apagado hasta confirmar las siete identidades, las reglas de multiagencia y la conservación de las asignaciones vigentes y cerradas. El ensayo local revierte por defecto. La confirmación optativa funciona exclusivamente en copias locales. Pruebe primero la concordancia de ambos orígenes con `E104_VERIFICAR_ASIGNACION_CAJA`, y compruebe aperturas, traslados, cambios de rol y bajas de agencia antes del corte. Conserve la tabla histórica de CooperativaDB durante la transición.
