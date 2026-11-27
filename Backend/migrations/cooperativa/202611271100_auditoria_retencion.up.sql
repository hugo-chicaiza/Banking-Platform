/* E8-02 · Retención y archivo de la bitácora (AU-8). Sin purga: los años de retención solo documentan el plazo. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57612,'Confirme la base cooperativa.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'Parametros.Parametro',N'U') IS NULL OR OBJECT_ID(N'Parametros.ParametroValor',N'U') IS NULL
    THROW 57612,'Falta el catalogo E0-09.',1;
 DECLARE @p TABLE(Clave varchar(60) COLLATE Latin1_General_100_BIN2, Descripcion nvarchar(200), Valor varchar(10));
 INSERT @p VALUES
  ('AUD_RETENCION_ANIOS', N'Años que se conserva la bitácora de auditoría', '7'),
  ('TRX_RETENCION_ANIOS', N'Años que se conservan transacciones, asientos y comprobantes (a confirmar con el contador)', '10'),
  ('AUD_EDAD_ARCHIVO_ANIOS', N'Edad en años a partir de la cual la bitácora pasa al archivo', '2');
 INSERT Parametros.Parametro (Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,ValorMaximo,EsSensible,AdmiteAgencia)
 SELECT p.Clave,'Auditoria',p.Descripcion,'Entero','anios',1,50,0,0 FROM @p p
 WHERE NOT EXISTS (SELECT 1 FROM Parametros.Parametro x WITH (UPDLOCK,HOLDLOCK) WHERE x.Clave=p.Clave);
 IF EXISTS (SELECT 1 FROM Parametros.Parametro x JOIN @p p ON p.Clave=x.Clave WHERE x.TipoDato<>'Entero' OR x.AdmiteAgencia<>0)
    THROW 57612,'La definicion existente de un parametro de retencion es incompatible.',1;
 INSERT Parametros.ParametroValor (IdParametro,Valor,VigenciaDesde,CreadoPor)
 SELECT x.IdParametro,p.Valor,'19000101',NULL FROM Parametros.Parametro x JOIN @p p ON p.Clave=x.Clave
 WHERE NOT EXISTS (SELECT 1 FROM Parametros.ParametroValor v WITH (UPDLOCK,HOLDLOCK) WHERE v.IdParametro=x.IdParametro);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
