-- Dependencia minima E0-06 para tareas persistidas E0-08; no cambia trabajos ATM.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57390,'Falta confirmar la base destino.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF SCHEMA_ID('Sistema') IS NULL EXEC('CREATE SCHEMA Sistema');
 IF OBJECT_ID('Sistema.Tarea','U') IS NULL
  CREATE TABLE Sistema.Tarea(Codigo varchar(40) NOT NULL CONSTRAINT PK_T_E008 PRIMARY KEY,
   Descripcion nvarchar(200) NOT NULL,Modulo varchar(30) NOT NULL,Programacion varchar(60) NOT NULL,
   PermiteManual bit NOT NULL,Estado char(1) NOT NULL CONSTRAINT DF_T_E008_Estado DEFAULT 'A');
 ELSE IF COL_LENGTH('Sistema.Tarea','PermiteManual') IS NULL
  THROW 57390,'Catalogo de tareas incompatible.',1;
 IF OBJECT_ID('Sistema.TareaEjecucion','U') IS NULL
  CREATE TABLE Sistema.TareaEjecucion(
   IdEjecucion bigint IDENTITY NOT NULL CONSTRAINT PK_TE_E008 PRIMARY KEY,
   Codigo varchar(40) NOT NULL CONSTRAINT FK_TE_E008_Tarea REFERENCES Sistema.Tarea(Codigo),
   InicioUTC datetime2(7) NOT NULL CONSTRAINT DF_TE_E008_Inicio DEFAULT SYSUTCDATETIME(),
   FinUTC datetime2(7) NULL,Resultado varchar(10) NULL,
   Procesados int NOT NULL CONSTRAINT DF_TE_E008_Proc DEFAULT 0,
   Modificados int NOT NULL CONSTRAINT DF_TE_E008_Mod DEFAULT 0,
   CodigoError varchar(60) NULL,EjecutadaPor varchar(64) NULL,Motivo nvarchar(250) NULL,
   CONSTRAINT CK_TE_E008_Resultado CHECK(Resultado IN('Exitoso','Fallido','Parcial')),
   CONSTRAINT CK_TE_E008_Manual CHECK(EjecutadaPor IS NULL OR (Motivo IS NOT NULL AND LEN(LTRIM(RTRIM(Motivo)))>0))
  );
 ELSE IF ISNULL(COL_LENGTH('Sistema.TareaEjecucion','EjecutadaPor'),-1)<>64
  THROW 57390,'Registro de tareas incompatible.',1;
 IF OBJECT_ID('Sistema.ResumenAprobaciones','U') IS NULL
  CREATE TABLE Sistema.ResumenAprobaciones(
   IdOrganizacion varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,Fecha date NOT NULL,
   Contenido nvarchar(max) NOT NULL,FechaActualizacionUTC datetime2(7) NOT NULL,
   CONSTRAINT PK_RA_E008 PRIMARY KEY(IdOrganizacion,Fecha),CONSTRAINT CK_RA_E008_JSON CHECK(ISJSON(Contenido)=1));
 INSERT Sistema.Tarea(Codigo,Descripcion,Modulo,Programacion,PermiteManual)
 SELECT s.* FROM (VALUES
  ('APR_RECUPERACION',N'Recupera aprobadas y cancela pendientes sin acceso','Aprobaciones','cada minuto',1),
  ('APR_RESUMEN_ANTIGUAS',N'Resumen diario sin vencimiento de solicitudes','Aprobaciones','diaria',1),
  ('APR_AUD_RELEVO',N'Relevo idempotente de auditoria E0-08','Aprobaciones','cada minuto',1)
 )s(Codigo,Descripcion,Modulo,Programacion,PermiteManual)
 WHERE NOT EXISTS(SELECT 1 FROM Sistema.Tarea t WITH(UPDLOCK,HOLDLOCK) WHERE t.Codigo=s.Codigo);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
