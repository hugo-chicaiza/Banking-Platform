SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57610,'Confirme la base de seguridad.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'Seguridad.TransaccionesInterfaz',N'U') IS NULL
    OR OBJECT_ID(N'Auditoria.TipoEvento',N'U') IS NULL
    THROW 57610,'Faltan los catalogos de aprobaciones o auditoria.',1;
 IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK,HOLDLOCK)
                WHERE CodigoTransaccion='CON-PLANTILLA')
    INSERT Seguridad.TransaccionesInterfaz
      (CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
    VALUES ('CON-PLANTILLA',N'Programar plantilla contable','Contabilidad','cooperativa',N'["CONTADOR"]','con-plantilla-aprobar',1,'A');
 IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion='CON-PLANTILLA'
    AND BaseObjetivo='cooperativa' AND RolesEjecucion=N'["CONTADOR"]'
    AND PermisoAprobacion='con-plantilla-aprobar' AND EsSensible=1 AND Estado='A')
    THROW 57610,'La configuracion de CON-PLANTILLA es incompatible.',1;
 IF NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK,HOLDLOCK)
                WHERE CodigoEvento='CON_PLANTILLA_PROGRAMADA')
    INSERT Auditoria.TipoEvento (CodigoEvento,Modulo,Severidad,EnTransaccion)
    VALUES ('CON_PLANTILLA_PROGRAMADA','contabilidad','Sensible',1);
 IF NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento='CON_PLANTILLA_PROGRAMADA'
    AND Modulo='contabilidad' AND Severidad='Sensible' AND EnTransaccion=1 AND Estado='A')
    THROW 57610,'El evento CON_PLANTILLA_PROGRAMADA es incompatible.',1;
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
