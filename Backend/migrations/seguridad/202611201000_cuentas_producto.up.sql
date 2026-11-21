-- E3-05 #378 · operación de aprobación de asignaciones de cuentas y su evento.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57800,'Confirme la base de seguridad destino.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID('Seguridad.TransaccionesInterfaz','U') IS NULL OR OBJECT_ID('Auditoria.TipoEvento','U') IS NULL
  THROW 57800,'Faltan los catalogos de aprobaciones o auditoria existentes.',1;
 IF EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='CON-MAPEO'
   AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["CONTADOR"]' OR PermisoAprobacion<>'con-plantilla-aprobar' OR EsSensible<>1 OR Estado<>'A'))
  THROW 57800,'La operacion CON-MAPEO existente tiene otra definicion. No se sobrescribe.',1;
 IF NOT EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='CON-MAPEO')
  INSERT Seguridad.TransaccionesInterfaz(CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
  VALUES('CON-MAPEO',N'Asignar cuentas contables a productos','Contabilidad','cooperativa',N'["CONTADOR"]','con-plantilla-aprobar',1,'A');
 IF EXISTS(SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento='CON_MAPEO_PROGRAMADO' AND (Modulo<>'contabilidad' OR Severidad<>'Sensible' OR EnTransaccion<>1 OR Estado<>'A'))
  THROW 57800,'El evento existente es incompatible.',1;
 IF NOT EXISTS(SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento='CON_MAPEO_PROGRAMADO')
  INSERT Auditoria.TipoEvento(CodigoEvento,Modulo,Severidad,EnTransaccion) VALUES('CON_MAPEO_PROGRAMADO','contabilidad','Sensible',1);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
