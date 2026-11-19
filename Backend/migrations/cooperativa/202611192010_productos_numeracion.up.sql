-- E3-04. Propuesta: no ejecutar en Azure sin autorizacion del SQL definitivo.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57700,'Confirme la base destino de numeracion.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID('ProductosFinancieros.ReglaNumeracion','U') IS NULL OR OBJECT_ID('ProductosFinancieros.SecuenciaCuenta','U') IS NULL
  THROW 57700,'Faltan las tablas base E3-01. No se crean catalogos sustitutos.',1;
 IF COL_LENGTH('ProductosFinancieros.ReglaNumeracion','IncluyeAgencia') IS NULL
 BEGIN
  IF EXISTS(SELECT 1 FROM ProductosFinancieros.ReglaNumeracion WITH(TABLOCKX,HOLDLOCK)) OR EXISTS(SELECT 1 FROM ProductosFinancieros.SecuenciaCuenta WITH(TABLOCKX,HOLDLOCK))
   THROW 57700,'Las tablas base dejaron de estar vacias: revisar sus datos antes de ampliar.',1;
  ALTER TABLE ProductosFinancieros.ReglaNumeracion ADD
   IncluyeAgencia bit NOT NULL CONSTRAINT DF_E304_IncluyeAgencia DEFAULT(0),
   AlgoritmoVerificador varchar(15) NOT NULL CONSTRAINT DF_E304_Algoritmo DEFAULT('NINGUNO'),
   Usada bit NOT NULL CONSTRAINT DF_E304_Usada DEFAULT(0),
   IdSolicitud bigint NULL,
   CreadoPor int NULL,
   IdReglaSecuencia int NULL CONSTRAINT FK_E304_Regla_Serie REFERENCES ProductosFinancieros.ReglaNumeracion(IdReglaNumeracion);
 END;
 IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name='CK_E304_Regla_Formato' AND parent_object_id=OBJECT_ID('ProductosFinancieros.ReglaNumeracion'))
 EXEC sys.sp_executesql N'ALTER TABLE ProductosFinancieros.ReglaNumeracion WITH CHECK ADD CONSTRAINT CK_E304_Regla_Formato CHECK (LEN(Prefijo) BETWEEN 1 AND 6 AND Prefijo NOT LIKE ''%[^0-9]%'' AND LongitudSecuencia BETWEEN 6 AND 10 AND AlgoritmoVerificador IN(''NINGUNO'',''MODULO_10'',''MODULO_11'') AND (IdReglaSecuencia IS NULL OR IdReglaSecuencia<>IdReglaNumeracion))';
 IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('ProductosFinancieros.ReglaNumeracion') AND name='UX_E304_Regla_Activa')
  CREATE UNIQUE INDEX UX_E304_Regla_Activa ON ProductosFinancieros.ReglaNumeracion(IdSubProducto) WHERE Estado='A';
 IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('ProductosFinancieros.ReglaNumeracion') AND name='UX_E304_Regla_Solicitud')
  EXEC sys.sp_executesql N'CREATE UNIQUE INDEX UX_E304_Regla_Solicitud ON ProductosFinancieros.ReglaNumeracion(IdSolicitud) WHERE IdSolicitud IS NOT NULL';
 -- El mismo formato comparte un solo contador, tambien entre agencias.
 -- Las reglas previas no se reescriben: una correccion sin uso crea otra version.
 EXEC sys.sp_executesql N'
 INSERT ProductosFinancieros.ReglaNumeracion(IdSubProducto,Prefijo,LongitudSecuencia,VigenciaDesde,Estado,IncluyeAgencia,AlgoritmoVerificador,Usada)
 SELECT s.IdSubProducto,''2200'',8,CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time''),''A'',0,''NINGUNO'',1
 FROM ProductosFinancieros.SubProducto s
 WHERE s.CodigoSubProducto IN(''AHO001-PN'',''AHO001-PJ'') AND NOT EXISTS(SELECT 1 FROM ProductosFinancieros.ReglaNumeracion r WHERE r.IdSubProducto=s.IdSubProducto);
 DECLARE @raiz int=(SELECT MIN(IdReglaNumeracion) FROM ProductosFinancieros.ReglaNumeracion WHERE Prefijo=''2200'' AND LongitudSecuencia=8 AND IncluyeAgencia=0 AND AlgoritmoVerificador=''NINGUNO'');
 IF @raiz IS NOT NULL
 BEGIN
  UPDATE ProductosFinancieros.ReglaNumeracion SET IdReglaSecuencia=@raiz WHERE IdReglaNumeracion<>@raiz AND Prefijo=''2200'' AND LongitudSecuencia=8 AND IncluyeAgencia=0 AND AlgoritmoVerificador=''NINGUNO'' AND IdReglaSecuencia IS NULL;
  IF NOT EXISTS(SELECT 1 FROM ProductosFinancieros.SecuenciaCuenta WHERE IdReglaNumeracion=@raiz)
   INSERT ProductosFinancieros.SecuenciaCuenta(IdReglaNumeracion,UltimoNumero) SELECT @raiz,COALESCE(MAX(TRY_CONVERT(bigint,RIGHT(NumeroCuenta,8))),0) FROM Cuentas.Cuenta WHERE LEN(NumeroCuenta)=12 AND NumeroCuenta LIKE ''2200[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'';
 END';
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_E304_Regla_EnUso ON ProductosFinancieros.ReglaNumeracion AFTER INSERT,UPDATE,DELETE AS
 BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM deleted d LEFT JOIN inserted i ON i.IdReglaNumeracion=d.IdReglaNumeracion WHERE d.Usada=1 AND (i.IdReglaNumeracion IS NULL OR i.Usada=0 OR i.Prefijo<>d.Prefijo OR i.IncluyeAgencia<>d.IncluyeAgencia OR i.LongitudSecuencia<>d.LongitudSecuencia OR i.AlgoritmoVerificador<>d.AlgoritmoVerificador OR i.Estado<>d.Estado OR ISNULL(i.IdReglaSecuencia,-1)<>ISNULL(d.IdReglaSecuencia,-1) OR i.VigenciaDesde<>d.VigenciaDesde OR ISNULL(i.VigenciaHasta,CONVERT(date,''99991231'',112))<>ISNULL(d.VigenciaHasta,CONVERT(date,''99991231'',112))))
  THROW 57702,''REGLA_EN_USO: no se modifica una regla utilizada.'',1;
 IF EXISTS(SELECT 1 FROM inserted i WHERE NOT EXISTS(SELECT 1 FROM deleted d WHERE d.IdReglaNumeracion=i.IdReglaNumeracion) AND EXISTS(SELECT 1 FROM Cuentas.Cuenta c WHERE c.IdSubProducto=i.IdSubProducto))
  THROW 57702,''REGLA_EN_USO: el subproducto ya tiene cuentas.'',1;
 END';
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
