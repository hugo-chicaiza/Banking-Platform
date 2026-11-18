-- Autorizacion adicional: proteger solo filas nuevas enriquecidas de E0-08.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57390,'Falta confirmar la base destino.',1;
IF OBJECT_ID('Auditoria.Auditoria','U') IS NULL
 THROW 57390,'Falta la bitacora institucional.',1;
IF NOT EXISTS(SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('Auditoria.Auditoria') AND name='AuditoriaID' AND TYPE_NAME(user_type_id)='int')
 THROW 57390,'Identificador institucional incompatible.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF OBJECT_ID('Auditoria.EventoDetalle','U') IS NULL
 BEGIN
  CREATE TABLE Auditoria.EventoDetalle(
   IdEvento uniqueidentifier NOT NULL CONSTRAINT PK_ED_E008 PRIMARY KEY,
   AuditoriaID int NOT NULL CONSTRAINT UQ_ED_E008_Auditoria UNIQUE,
   CodigoEvento varchar(40) NOT NULL,Contenido nvarchar(max) NOT NULL,
   FechaHoraUTC datetime2(7) NOT NULL,
   CONSTRAINT FK_ED_E008_Auditoria FOREIGN KEY(AuditoriaID) REFERENCES Auditoria.Auditoria(AuditoriaID),
   CONSTRAINT CK_ED_E008_JSON CHECK(ISJSON(Contenido)=1)
  );
  EXEC(N'CREATE TRIGGER Auditoria.trg_ED_E008_Inmutable ON Auditoria.EventoDetalle AFTER UPDATE,DELETE AS BEGIN SET NOCOUNT ON; THROW 57201,''El detalle de auditoria es inmutable.'',1; END');
 END
 ELSE IF ISNULL(COL_LENGTH('Auditoria.EventoDetalle','AuditoriaID'),-1)<>4 OR OBJECT_ID('Auditoria.trg_ED_E008_Inmutable','TR') IS NULL
  THROW 57390,'Detalle de auditoria incompatible.',1;
 IF OBJECT_ID('Auditoria.trg_Auditoria_E008_Protegida','TR') IS NULL
  EXEC(N'CREATE TRIGGER Auditoria.trg_Auditoria_E008_Protegida ON Auditoria.Auditoria AFTER UPDATE AS
   BEGIN
    SET NOCOUNT ON;
    IF EXISTS(SELECT 1 FROM deleted d JOIN Auditoria.EventoDetalle e ON e.AuditoriaID=d.AuditoriaID)
     THROW 57201,''El evento institucional registrado es inmutable.'',1;
   END');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
