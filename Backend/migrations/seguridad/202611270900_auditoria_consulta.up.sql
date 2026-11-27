/* E8-01 · Consulta de la bitácora de auditoría (SeguridadDB). Aditiva.
   - TipoEvento: AUD_LECTURA (lectura auditada) y AUD_EXPORTACION (exportación).
   - Índice IX_Auditoria_UsuarioFecha para búsquedas por usuario y rango de fecha. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57205,'Falta confirmar la base destino de E8-01.',1;
IF DB_NAME()<>N'SeguridadDB' THROW 57205,'La migracion requiere SeguridadDB.',1;
BEGIN TRANSACTION;
BEGIN TRY
 INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
 SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
 FROM (VALUES ('AUD_LECTURA', 'auditoria', 'Seguridad', 0),
              ('AUD_EXPORTACION', 'auditoria', 'Sensible', 0))
     AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
 WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
                   WHERE CodigoEvento = e.CodigoEvento);
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'IX_Auditoria_UsuarioFecha','IndexID') IS NULL
  EXEC('CREATE INDEX IX_Auditoria_UsuarioFecha ON Auditoria.Auditoria(UsuarioID, FechaHoraUTC)');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
