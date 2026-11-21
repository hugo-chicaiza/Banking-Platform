-- E0-09. Aditiva; no altera objetos existentes de otros modulos.
-- El ejecutor fija migration_database tras verificar entorno y servidor.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57190,'Falta confirmar la base destino de la migracion.',1;
IF OBJECT_ID(N'Organizacion.Agencia',N'U') IS NULL
 THROW 57190,'Falta la dependencia Organizacion.Agencia.',1;
IF NOT EXISTS(SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'Organizacion.Agencia') AND name='IdAgencia' AND TYPE_NAME(user_type_id)='char' AND max_length=3)
 THROW 57190,'IdAgencia no coincide con el contrato char(3).',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF SCHEMA_ID('Parametros') IS NULL EXEC('CREATE SCHEMA Parametros');
 IF OBJECT_ID('Parametros.Parametro','U') IS NULL AND OBJECT_ID('Parametros.ParametroValor','U') IS NULL
 BEGIN
  CREATE TABLE Parametros.Parametro (
   IdParametro int IDENTITY NOT NULL CONSTRAINT PK_Parametro PRIMARY KEY,
   Clave varchar(60) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT UQ_Parametro_Clave UNIQUE,
   Modulo varchar(30) NOT NULL,Descripcion nvarchar(250) NOT NULL,
   TipoDato varchar(10) COLLATE Latin1_General_100_BIN2 NOT NULL,Unidad varchar(15) NULL,
   ValorMinimo decimal(18,4) NULL,ValorMaximo decimal(18,4) NULL,
   ValoresPermitidos nvarchar(2000) NULL,
   EsSensible bit NOT NULL CONSTRAINT DF_Parametro_EsSensible DEFAULT 0,
   AdmiteAgencia bit NOT NULL CONSTRAINT DF_Parametro_AdmiteAgencia DEFAULT 0,
   Estado char(1) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT DF_Parametro_Estado DEFAULT 'A',
   Version rowversion NOT NULL,
   CONSTRAINT CK_Parametro_Clave CHECK(LEN(Clave)>0 AND Clave NOT LIKE '%[^A-Z0-9_]%'),
   CONSTRAINT CK_Parametro_TipoDato CHECK(TipoDato IN ('Entero','Decimal','Texto','Booleano','Hora','Lista')),
   CONSTRAINT CK_Parametro_Rango CHECK(ValorMinimo IS NULL OR ValorMaximo IS NULL OR ValorMinimo<=ValorMaximo),
   CONSTRAINT CK_Parametro_Permitidos CHECK(ValoresPermitidos IS NULL OR (ISJSON(ValoresPermitidos)=1 AND LEFT(LTRIM(ValoresPermitidos),1)='[')),
   CONSTRAINT CK_Parametro_Estado CHECK(Estado IN ('A','I'))
  );
  CREATE TABLE Parametros.ParametroValor (
   IdParametroValor int IDENTITY NOT NULL CONSTRAINT PK_ParametroValor PRIMARY KEY,
   IdParametro int NOT NULL,IdAgencia char(3) NULL,Valor nvarchar(500) NOT NULL,
   VigenciaDesde date NOT NULL,VigenciaHasta date NULL,
   Estado char(1) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT DF_ParametroValor_Estado DEFAULT 'A',
   IdSolicitud bigint NULL,CreadoPor varchar(64) NULL,
   FechaCreacion datetime2(7) NOT NULL CONSTRAINT DF_ParametroValor_Fecha DEFAULT SYSUTCDATETIME(),
   IdValorAnterior int NULL,VigenciaHastaAnterior date NULL,Version rowversion NOT NULL,
   CONSTRAINT FK_ParametroValor_Parametro FOREIGN KEY(IdParametro) REFERENCES Parametros.Parametro(IdParametro),
   CONSTRAINT FK_ParametroValor_Agencia FOREIGN KEY(IdAgencia) REFERENCES Organizacion.Agencia(IdAgencia),
   CONSTRAINT FK_ParametroValor_Anterior FOREIGN KEY(IdValorAnterior) REFERENCES Parametros.ParametroValor(IdParametroValor),
   CONSTRAINT CK_ParametroValor_Actor CHECK(CreadoPor IS NULL OR (CreadoPor LIKE 'user[_]%' AND LEN(CreadoPor)>5)),
   CONSTRAINT CK_ParametroValor_Vigencia CHECK(VigenciaHasta IS NULL OR VigenciaHasta>=VigenciaDesde),
   CONSTRAINT CK_ParametroValor_Estado CHECK(Estado IN ('A','C'))
  );
  CREATE INDEX IX_ParametroValor_Vigencia ON Parametros.ParametroValor(IdParametro,IdAgencia,VigenciaDesde) INCLUDE(Valor,VigenciaHasta,Estado);
  CREATE UNIQUE INDEX UX_ParametroValor_Solicitud ON Parametros.ParametroValor(IdSolicitud) WHERE IdSolicitud IS NOT NULL;
  EXEC(N'CREATE TRIGGER Parametros.trg_ParametroValor_SinSolape ON Parametros.ParametroValor AFTER INSERT,UPDATE AS
   BEGIN
    SET NOCOUNT ON;
    IF EXISTS(SELECT 1 FROM inserted i JOIN Parametros.ParametroValor v WITH(UPDLOCK,HOLDLOCK)
     ON v.IdParametro=i.IdParametro AND (v.IdAgencia=i.IdAgencia OR(v.IdAgencia IS NULL AND i.IdAgencia IS NULL))
     AND v.IdParametroValor<>i.IdParametroValor AND v.Estado=''A'' AND i.Estado=''A''
     AND v.VigenciaDesde<=ISNULL(i.VigenciaHasta,CONVERT(date,''99991231'',112))
     AND i.VigenciaDesde<=ISNULL(v.VigenciaHasta,CONVERT(date,''99991231'',112)))
      THROW 57101,''Vigencia solapada para el mismo parametro y alcance.'',1;
   END');
 END
 ELSE
 BEGIN
  -- Nunca corregir silenciosamente una tabla parcial o de otra version.
  IF OBJECT_ID('Parametros.Parametro','U') IS NULL OR OBJECT_ID('Parametros.ParametroValor','U') IS NULL
   THROW 57190,'Instalacion parcial: requiere revision manual.',1;
  IF ISNULL(COL_LENGTH('Parametros.Parametro','ValoresPermitidos'),-1)<>4000
    OR ISNULL(COL_LENGTH('Parametros.ParametroValor','CreadoPor'),-1)<>64
    OR ISNULL(COL_LENGTH('Parametros.ParametroValor','IdValorAnterior'),-1)<>4
    OR OBJECT_ID('Parametros.trg_ParametroValor_SinSolape','TR') IS NULL
    OR NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('Parametros.ParametroValor') AND name='UX_ParametroValor_Solicitud')
   THROW 57190,'Objetos de parametros incompatibles: no se modificaron.',1;
 END;
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
