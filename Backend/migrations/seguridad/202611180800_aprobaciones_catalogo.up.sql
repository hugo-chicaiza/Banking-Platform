-- Catalogo de operaciones, no directorio de usuarios ni sustituto de WorkOS.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57390,'Falta confirmar la base destino.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF SCHEMA_ID('Seguridad') IS NULL EXEC('CREATE SCHEMA Seguridad');
 IF OBJECT_ID('Seguridad.TransaccionesInterfaz','U') IS NULL
 BEGIN
  CREATE TABLE Seguridad.TransaccionesInterfaz(
   CodigoTransaccion varchar(20) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT PK_TI_E008 PRIMARY KEY,
   NombreTransaccion nvarchar(100) NOT NULL,Modulo varchar(30) NOT NULL,
   BaseObjetivo varchar(12) NOT NULL,
   RolesEjecucion nvarchar(300) NOT NULL,PermisoAprobacion varchar(100) NOT NULL,
   EsSensible bit NOT NULL CONSTRAINT DF_TI_E008_Sensible DEFAULT 1,
   Estado char(1) NOT NULL CONSTRAINT DF_TI_E008_Estado DEFAULT 'A',
   CONSTRAINT CK_TI_E008_Base CHECK(BaseObjetivo IN ('cooperativa','seguridad')),
   CONSTRAINT CK_TI_E008_Roles CHECK(ISJSON(RolesEjecucion)=1 AND LEFT(LTRIM(RolesEjecucion),1)='['),
   CONSTRAINT CK_TI_E008_Estado CHECK(Estado IN ('A','I'))
  );
 END
 ELSE IF COL_LENGTH('Seguridad.TransaccionesInterfaz','PermisoAprobacion') IS NULL
  THROW 57390,'Catalogo existente incompatible; no se modifico.',1;
 -- Las reglas de ejecucion reflejan develop; las aprobaciones son slugs acordados.
 INSERT Seguridad.TransaccionesInterfaz(CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion)
 SELECT s.* FROM (VALUES
  ('PAR-EDITAR',N'Programar valores de parametros','Parametros','cooperativa',N'["ADMIN"]','parametros:aprobar'),
  ('ORG-AGENCIA-EDITAR',N'Cambios sensibles de agencias','Organizacion','cooperativa',N'["ADMIN"]','agencias:aprobar')
 )s(Codigo,Nombre,Modulo,BaseObjetivo,RolesEjecucion,Permiso)
 WHERE NOT EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz t WITH(UPDLOCK,HOLDLOCK) WHERE t.CodigoTransaccion=s.Codigo);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
