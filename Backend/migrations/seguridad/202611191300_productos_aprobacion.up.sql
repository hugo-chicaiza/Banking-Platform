SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57603,'Falta confirmar la base destino de E3-03.',1;
IF CONVERT(int,SERVERPROPERTY('EngineEdition'))=5 AND ISNULL(CONVERT(int,SESSION_CONTEXT(N'E303_AZURE_APROBADA')),0)<>1
    THROW 57603,'E3-03 requiere autorizacion adicional para Azure.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID('Seguridad.TransaccionesInterfaz','U') IS NULL
   THROW 57603,'Falta el catalogo E0-08.',1;
 IF OBJECT_ID('Auditoria.TipoEvento','U') IS NULL
   THROW 57603,'Falta el catalogo de eventos E0-05 integrado en develop.',1;
 IF EXISTS(SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento IN ('PRD_CONDICION_PROGRAMADA','PRD_CUPO_PROGRAMADO','PRD_RESTRICCION_PROGRAMADA','PRD_PROGRAMACION_CANCELADA')
   AND (Modulo<>'productos' OR Severidad<>'Sensible' OR EnTransaccion<>1 OR Estado<>'A'))
   THROW 57603,'Un evento E3-03 existente tiene una definicion incompatible.',1;
 MERGE Auditoria.TipoEvento AS d USING (VALUES
   ('PRD_CONDICION_PROGRAMADA', 'productos', 'Sensible', 1),
   ('PRD_CUPO_PROGRAMADO', 'productos', 'Sensible', 1),
   ('PRD_RESTRICCION_PROGRAMADA', 'productos', 'Sensible', 1),
   ('PRD_PROGRAMACION_CANCELADA', 'productos', 'Sensible', 1)
 ) AS o(CodigoEvento,Modulo,Severidad,EnTransaccion) ON d.CodigoEvento=o.CodigoEvento
 WHEN NOT MATCHED THEN INSERT(CodigoEvento,Modulo,Severidad,EnTransaccion)
   VALUES(o.CodigoEvento,o.Modulo,o.Severidad,o.EnTransaccion);
 IF EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='PRD-CONDICION'
   AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["ADMIN"]' OR PermisoAprobacion<>'productos:aprobar' OR EsSensible<>1 OR Estado<>'A'))
   THROW 57603,'La operacion PRD-CONDICION existente es incompatible; no se sobrescribe.',1;
 IF NOT EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='PRD-CONDICION')
   INSERT Seguridad.TransaccionesInterfaz(CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
   VALUES('PRD-CONDICION',N'Programar condiciones, cupos y restricciones','Productos','cooperativa',N'["ADMIN"]','productos:aprobar',1,'A');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
