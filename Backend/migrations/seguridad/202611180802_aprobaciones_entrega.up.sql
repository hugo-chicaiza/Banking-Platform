-- E0-08: comprobante idempotente y bandeja transaccional; solo objetos nuevos.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57390,'Falta confirmar la base destino.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF SCHEMA_ID('Seguridad') IS NULL EXEC('CREATE SCHEMA Seguridad');
 IF SCHEMA_ID('Auditoria') IS NULL EXEC('CREATE SCHEMA Auditoria');
 IF OBJECT_ID('Seguridad.AprobacionAplicada','U') IS NULL
  CREATE TABLE Seguridad.AprobacionAplicada(
   IdOrganizacion varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
   IdSolicitud bigint NOT NULL,HashContenido binary(32) NOT NULL,
   CodigoTransaccion varchar(20) NOT NULL,
   FechaEjecucionUTC datetime2(7) NOT NULL CONSTRAINT DF_AA_E008_Fecha DEFAULT SYSUTCDATETIME(),
   CONSTRAINT PK_AA_E008 PRIMARY KEY(IdOrganizacion,IdSolicitud)
  );
 ELSE IF ISNULL(COL_LENGTH('Seguridad.AprobacionAplicada','HashContenido'),-1)<>32
  THROW 57390,'Comprobante existente incompatible.',1;
 IF OBJECT_ID('Auditoria.EventoPendiente','U') IS NULL
 BEGIN
  CREATE TABLE Auditoria.EventoPendiente(
   IdEvento uniqueidentifier NOT NULL CONSTRAINT PK_EP_E008 PRIMARY KEY,
   CodigoEvento varchar(40) NOT NULL,Contenido nvarchar(max) NOT NULL,
   FechaCreacionUTC datetime2(7) NOT NULL CONSTRAINT DF_EP_E008_Fecha DEFAULT SYSUTCDATETIME(),
   Enviado bit NOT NULL CONSTRAINT DF_EP_E008_Enviado DEFAULT 0,
   Intentos int NOT NULL CONSTRAINT DF_EP_E008_Intentos DEFAULT 0,
   CONSTRAINT CK_EP_E008_JSON CHECK(ISJSON(Contenido)=1)
  );
  CREATE INDEX IX_EP_E008_Orden ON Auditoria.EventoPendiente(Enviado,FechaCreacionUTC);
 END
 ELSE IF COL_LENGTH('Auditoria.EventoPendiente','Contenido') IS NULL
  THROW 57390,'Bandeja de auditoria existente incompatible.',1;
 IF OBJECT_ID('Seguridad.trg_AA_E008_Inmutable','TR') IS NULL
  EXEC(N'CREATE TRIGGER Seguridad.trg_AA_E008_Inmutable ON Seguridad.AprobacionAplicada AFTER UPDATE,DELETE AS BEGIN SET NOCOUNT ON; THROW 57001,''El comprobante no se modifica ni elimina.'',1; END');
 IF OBJECT_ID('Auditoria.trg_EP_E008_Contenido','TR') IS NULL
  EXEC(N'CREATE TRIGGER Auditoria.trg_EP_E008_Contenido ON Auditoria.EventoPendiente AFTER UPDATE,DELETE AS
   BEGIN
    SET NOCOUNT ON;
    IF EXISTS(SELECT 1 FROM deleted d LEFT JOIN inserted i ON i.IdEvento=d.IdEvento WHERE i.IdEvento IS NULL)
     THROW 57201,''El evento pendiente no se elimina.'',1;
    IF UPDATE(IdEvento) OR UPDATE(CodigoEvento) OR UPDATE(Contenido) OR UPDATE(FechaCreacionUTC)
     THROW 57201,''El evento pendiente no se modifica.'',1;
   END');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
