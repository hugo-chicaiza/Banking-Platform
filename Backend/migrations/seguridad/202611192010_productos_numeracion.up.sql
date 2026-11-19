-- Propuesta E3-04: solo despues de autorizacion y pruebas locales.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57700,'Confirme la base de seguridad destino.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID('Seguridad.TransaccionesInterfaz','U') IS NULL OR OBJECT_ID('Auditoria.TipoEvento','U') IS NULL
  THROW 57700,'Faltan los catalogos de aprobaciones o auditoria existentes.',1;
 IF EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='PRD-NUMERACION' AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["ADMIN"]' OR PermisoAprobacion<>'productos:aprobar' OR EsSensible<>1 OR Estado<>'A'))
  THROW 57700,'La operacion existente tiene otra definicion. No se sobrescribe.',1;
 IF NOT EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='PRD-NUMERACION')
  INSERT Seguridad.TransaccionesInterfaz(CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
  VALUES('PRD-NUMERACION',N'Definir numeracion de cuentas','Productos','cooperativa',N'["ADMIN"]','productos:aprobar',1,'A');
 IF EXISTS(SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento='PRD_NUMERACION_DEFINIDA' AND (Modulo<>'productos' OR Severidad<>'Sensible' OR EnTransaccion<>1 OR Estado<>'A'))
  THROW 57700,'El evento existente es incompatible.',1;
 IF NOT EXISTS(SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento='PRD_NUMERACION_DEFINIDA')
  INSERT Auditoria.TipoEvento(CodigoEvento,Modulo,Severidad,EnTransaccion) VALUES('PRD_NUMERACION_DEFINIDA','productos','Sensible',1);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
