# E2-01 · aprobación institucional por WorkOS

El criterio 5 separa a las personas que preparan y aprueban. En la API
ambas sesiones WorkOS pueden utilizar el mismo principal privado de servicio
en SQL Server. El canal SSMS de 004 sigue verificando dos identidades SQL
distintas cuando se usa ese canal.

## Instalación manual con 004 instalado

1. Revisar y ejecutar scripts/sql/e201/006_aprobacion_workos.sql. La
   migración conserva el verificador SSMS anterior y lo despacha para
   sus recibos positivos. Los recibos institucionales tienen IDs negativos.
2. El DBA debe vincular un principal SQL **privado de la API**, de mínimo
   privilegio, al rol E201_ServicioWorkOS. Darle acceso únicamente al
   procedimiento delegado por ese rol. La credencial no se comparte con
   operadores ni se concede el rol a devcat, al login de la aplicación
   general o a identidades humanas. Mantener al principal fuera de
   db_owner, db_datawriter y de roles de corte SSMS. Si devcat tiene
   privilegios de administración, sigue siendo parte de la frontera de
   confianza administrativa de toda la base.
3. Configurar WORKOS_ORGANIZATION_ID y las variables privadas
   E201_SERVICIO_SQL_USER y E201_SERVICIO_SQL_PASSWORD. Publicar en WorkOS
   con-reclasificacion-preparar y con-reclasificacion-aprobar y asignarlos
   a los usuarios aprobados. Registrar el vínculo local según el procedimiento
   de dos bases descrito abajo. El backend revalida al actor contra SeguridadDB
   y, al aprobar, también verifica el vínculo vigente del preparador.
4. Desplegar la API. Bajo el prefijo /contabilidad/cortes-e201:
   - POST guarda el manifiesto. El cuerpo contiene IdCorte, FechaCorte,
     NumeroAsiento, IdFechaContable, IdAgencia, Controles y ConciliacionAhorro.
     La API genera IdPlan y SQL resuelve PreparadoPor desde la sesión
     institucional. Devuelve Contenido y HashPlan.
   - GET /{id_plan} permite a un aprobador ver el manifiesto congelado.
   - POST /{id_plan}/aprobaciones recibe hashPlan y comentario. El sujeto
     proviene de la sesión autenticada. La base verifica el hash, la
     separación de personas y la versión del objetivo, y emite el recibo.
5. Un ejecutor habilitado de SSMS llama E201.usp_EjecutarCorte con el
   IdSolicitud exacto, incluido su signo. El procedimiento existente
   revalida recibo, vínculos y permisos locales de BD y ejecuta el
   mismo corte atómico. Conservar el ticket, hash y el asiento en la
   evidencia de despliegue.

No aplicar 004 de nuevo tras 006. Su última sección reinstala el validador
exclusivo de SSMS. Desactivar el canal API retirando el rol del principal
privado. Para detener un recibo institucional aún pendiente, retirar el
permiso efectivo en E201.PermisoWorkOS antes de ejecutar el corte. Los
asientos confirmados siguen el procedimiento de recuperación de E2-01.

## Recuperación de 1767 / 1750 y vínculo entre bases

En la inspección posterior al error, CooperativaDB solo mostró el
validador de 004, sin rol ni objetos WorkOS visibles. SeguridadDB sí
contiene Organizacion.Usuarios. Antes de aplicar, usar
006_diagnostico_solo_lectura.sql en SSMS como DBA para confirmar el estado
con visibilidad completa. En la sesión fallida, si quedó una transacción
abierta de 006, revertirla allí antes de abrir una pestaña nueva.

Usar el 006 corregido directamente después de 004. La instalación inicial
y la reiteración usan el mismo script. Si quedaron tablas de una versión
anterior, se conservan sus filas y se quita únicamente la FK antigua
local a Organizacion.Usuarios. Las habilitaciones antiguas que carecen
de sujeto y organización quedan inefectivas hasta su verificación.
No se crean objetos en SeguridadDB.

1. En una conexión directa a SeguridadDB, verificar los dos sujetos
   de WorkOS y exigir una fila Activo por sujeto y dos UsuarioID distintos.

       SELECT UsuarioID,KeyUsuario,Estado
       FROM Organizacion.Usuarios
       WHERE KeyUsuario IN ('<user_preparador>','<user_aprobador>');

2. En CooperativaDB, el DBA propietario registra cada vínculo comprobado
   con UsuarioID, Sujeto (KeyUsuario), Organizacion (org_... de dev),
   Preparar y Aprobar. El usuario de servicio no puede editar la tabla.
   Para un vínculo nuevo, usar:

       INSERT E201.PermisoWorkOS (UsuarioID,Sujeto,Organizacion,Preparar,Aprobar)
       VALUES (<id_preparador>,'<user_preparador>','<org_dev>',1,0),
              (<id_aprobador>,'<user_aprobador>','<org_dev>',0,1);

   Si la fila ya existe, actualizar por UsuarioID tras revisar sus datos.
   El vínculo local concede acceso al corte y no sustituye al padrón.
   El SQL no cruza bases ni usa una FK entre ellas.
3. Antes de ejecutar un recibo desde SSMS, consultar nuevamente en
   SeguridadDB que ambos vínculos del recibo sigan activos y coincidan con
   sus IDs. Ante baja, desvinculación o retiro de permiso, el DBA desactiva
   el permiso correspondiente en E201.PermisoWorkOS antes de ejecutar.
   El procedimiento de CooperativaDB valida el recibo y estos permisos
   locales dentro de la transacción. La ejecución desde SSMS no consulta
   SeguridadDB en vivo ni existe sincronización automática de revocaciones.
