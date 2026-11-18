-- Objetos nuevos E0-08. Sujetos canonicos WorkOS, sin nuevas asignaciones de roles.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57390,'Falta confirmar la base destino.',1;
IF OBJECT_ID('Seguridad.TransaccionesInterfaz','U') IS NULL
 THROW 57390,'Falta el catalogo de operaciones.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF OBJECT_ID('Seguridad.SolicitudAprobacion','U') IS NULL AND OBJECT_ID('Seguridad.SolicitudAprobacionEvento','U') IS NULL
 BEGIN
  CREATE TABLE Seguridad.SolicitudAprobacion(
   IdSolicitud bigint IDENTITY NOT NULL CONSTRAINT PK_SA_E008 PRIMARY KEY,
   IdOrganizacion varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
   CodigoTransaccion varchar(20) COLLATE Latin1_General_100_BIN2 NOT NULL,
   TipoObjetivo varchar(40) NOT NULL,IdObjetivo varchar(60) NOT NULL,IdAgencia char(3) NULL,
   Contenido nvarchar(max) NOT NULL,HashContenido binary(32) NOT NULL,
   Antes nvarchar(max) NOT NULL,Despues nvarchar(max) NOT NULL,VersionObjetivo varchar(64) NOT NULL,
   Estado varchar(12) NOT NULL CONSTRAINT DF_SA_E008_Estado DEFAULT 'Pendiente',
   EnCurso bit NOT NULL CONSTRAINT DF_SA_E008_EnCurso DEFAULT 1,
   SolicitadoPor varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
   NombreSolicitante nvarchar(150) NULL,IdInternoSolicitante int NULL,
   FechaSolicitud datetime2(7) NOT NULL CONSTRAINT DF_SA_E008_Fecha DEFAULT SYSUTCDATETIME(),
   ResueltoPor varchar(64) COLLATE Latin1_General_100_BIN2 NULL,
   NombreResolutor nvarchar(150) NULL,IdInternoResolutor int NULL,
   FechaResolucion datetime2(7) NULL,Comentario nvarchar(300) NULL,CodigoError varchar(60) NULL,
   Intentos int NOT NULL CONSTRAINT DF_SA_E008_Intentos DEFAULT 0,
   Alcance AS ISNULL(IdAgencia,'000') PERSISTED,
   Version rowversion NOT NULL,
   CONSTRAINT FK_SA_E008_Operacion FOREIGN KEY(CodigoTransaccion) REFERENCES Seguridad.TransaccionesInterfaz(CodigoTransaccion),
   CONSTRAINT CK_SA_E008_Estado CHECK(Estado IN ('Pendiente','Aprobada','Ejecutada','Rechazada','Cancelada','Fallida')),
   CONSTRAINT CK_SA_E008_EnCurso CHECK((Estado IN ('Pendiente','Aprobada') AND EnCurso=1) OR(Estado IN ('Ejecutada','Rechazada','Cancelada','Fallida') AND EnCurso=0)),
   CONSTRAINT CK_SA_E008_Personas CHECK(ResueltoPor IS NULL OR ResueltoPor<>SolicitadoPor),
   CONSTRAINT CK_SA_E008_JSON CHECK(ISJSON(Contenido)=1 AND ISJSON(Antes)=1 AND ISJSON(Despues)=1),
   CONSTRAINT CK_SA_E008_Resolucion CHECK((Estado='Pendiente' AND ResueltoPor IS NULL AND FechaResolucion IS NULL) OR(Estado='Cancelada' AND FechaResolucion IS NOT NULL) OR(Estado IN('Aprobada','Ejecutada','Rechazada','Fallida') AND ResueltoPor IS NOT NULL AND FechaResolucion IS NOT NULL))
  );
  CREATE UNIQUE INDEX UX_SA_E008_EnCurso ON Seguridad.SolicitudAprobacion(IdOrganizacion,CodigoTransaccion,TipoObjetivo,IdObjetivo,Alcance) WHERE EnCurso=1;
  CREATE INDEX IX_SA_E008_Bandeja ON Seguridad.SolicitudAprobacion(IdOrganizacion,Estado,IdAgencia,FechaSolicitud) INCLUDE(SolicitadoPor,CodigoTransaccion);
  CREATE TABLE Seguridad.SolicitudAprobacionEvento(
   IdEvento bigint IDENTITY NOT NULL CONSTRAINT PK_SAE_E008 PRIMARY KEY,
   IdSolicitud bigint NOT NULL CONSTRAINT FK_SAE_E008_Solicitud REFERENCES Seguridad.SolicitudAprobacion(IdSolicitud),
   EstadoAnterior varchar(12) NULL,EstadoNuevo varchar(12) NOT NULL,
   Sujeto varchar(64) NULL,Nombre nvarchar(150) NULL,IdInterno int NULL,
   Comentario nvarchar(300) NULL,
   FechaEvento datetime2(7) NOT NULL CONSTRAINT DF_SAE_E008_Fecha DEFAULT SYSUTCDATETIME()
  );
  EXEC(N'CREATE TRIGGER Seguridad.trg_SAE_E008_Inmutable ON Seguridad.SolicitudAprobacionEvento AFTER UPDATE,DELETE AS BEGIN SET NOCOUNT ON; THROW 57001,''El historial no se modifica ni elimina.'',1; END');
  EXEC(N'CREATE TRIGGER Seguridad.trg_SA_E008_Inmutable ON Seguridad.SolicitudAprobacion AFTER UPDATE,DELETE AS
   BEGIN
    SET NOCOUNT ON;
    IF EXISTS(SELECT 1 FROM deleted d LEFT JOIN inserted i ON i.IdSolicitud=d.IdSolicitud WHERE i.IdSolicitud IS NULL)
     THROW 57001,''La solicitud no se elimina.'',1;
    IF UPDATE(IdOrganizacion) OR UPDATE(CodigoTransaccion) OR UPDATE(TipoObjetivo) OR UPDATE(IdObjetivo) OR UPDATE(IdAgencia) OR UPDATE(Contenido) OR UPDATE(HashContenido) OR UPDATE(Antes) OR UPDATE(Despues) OR UPDATE(VersionObjetivo) OR UPDATE(SolicitadoPor) OR UPDATE(FechaSolicitud)
     THROW 57001,''El contenido congelado no se modifica.'',1;
    IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON i.IdSolicitud=d.IdSolicitud WHERE i.Estado<>d.Estado AND NOT((d.Estado=''Pendiente'' AND i.Estado IN(''Aprobada'',''Rechazada'',''Cancelada'')) OR(d.Estado=''Aprobada'' AND i.Estado IN(''Ejecutada'',''Fallida''))))
     THROW 57301,''Transicion no permitida.'',1;
   END');
 END
 ELSE IF OBJECT_ID('Seguridad.SolicitudAprobacion','U') IS NULL OR OBJECT_ID('Seguridad.SolicitudAprobacionEvento','U') IS NULL OR COL_LENGTH('Seguridad.SolicitudAprobacion','IdOrganizacion') IS NULL OR ISNULL(COL_LENGTH('Seguridad.SolicitudAprobacion','VersionObjetivo'),-1)<>64
  THROW 57390,'Instalacion parcial o incompatible; no se modifico.',1;
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
