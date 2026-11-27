/* E8-01 abajo: retira eventos sin uso y el índice. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57205,'Falta confirmar la base destino de E8-01.',1;
BEGIN TRANSACTION;
BEGIN TRY
 DELETE FROM Auditoria.TipoEvento
 WHERE CodigoEvento IN ('AUD_LECTURA', 'AUD_EXPORTACION')
   AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento);
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'IX_Auditoria_UsuarioFecha','IndexID') IS NOT NULL
  EXEC('DROP INDEX IX_Auditoria_UsuarioFecha ON Auditoria.Auditoria');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
