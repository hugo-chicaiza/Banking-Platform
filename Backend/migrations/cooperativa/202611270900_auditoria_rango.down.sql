SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57611,'Confirme la base cooperativa.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @id int;
 SELECT @id=IdParametro FROM Parametros.Parametro WHERE Clave='AUD_RANGO_MAX_DIAS';
 IF @id IS NOT NULL
 BEGIN
    DELETE FROM Parametros.ParametroValor WHERE IdParametro=@id;
    DELETE FROM Parametros.Parametro WHERE IdParametro=@id;
 END;
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
