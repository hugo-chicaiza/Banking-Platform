SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57611,'Confirme la base cooperativa.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'Parametros.Parametro',N'U') IS NULL
    OR OBJECT_ID(N'Parametros.ParametroValor',N'U') IS NULL
    THROW 57611,'Falta el catalogo E0-09.',1;
 DECLARE @id int;
 SELECT @id=IdParametro FROM Parametros.Parametro WITH (UPDLOCK,HOLDLOCK)
 WHERE Clave='AUD_RANGO_MAX_DIAS';
 IF @id IS NULL
 BEGIN
    INSERT Parametros.Parametro
      (Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,ValorMaximo,EsSensible,AdmiteAgencia)
    VALUES ('AUD_RANGO_MAX_DIAS','Auditoria',N'Rango maximo de dias para consultar la bitacora',
            'Entero','dias',1,366,0,0);
    SET @id=CONVERT(int,SCOPE_IDENTITY());
 END;
 IF NOT EXISTS (SELECT 1 FROM Parametros.Parametro WHERE IdParametro=@id
    AND TipoDato='Entero' AND AdmiteAgencia=0)
    THROW 57611,'La definicion existente del rango es incompatible.',1;
 IF NOT EXISTS (SELECT 1 FROM Parametros.ParametroValor WITH (UPDLOCK,HOLDLOCK) WHERE IdParametro=@id)
    INSERT Parametros.ParametroValor (IdParametro,Valor,VigenciaDesde,CreadoPor)
    VALUES (@id,'31','19000101',NULL);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
