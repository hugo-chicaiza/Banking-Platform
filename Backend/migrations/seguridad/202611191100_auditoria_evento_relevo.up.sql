/* E0-05 · Evento de la alerta del relevo de auditoría en el catálogo (SeguridadDB). Repetible. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57205,'Falta confirmar la base destino de la migracion.',1;
IF OBJECT_ID('Auditoria.TipoEvento','U') IS NULL THROW 57205,'Falta Auditoria.TipoEvento (202611191000).',1;
MERGE Auditoria.TipoEvento AS d USING (VALUES
  ('AUD_RELEVO_ALERTA', 'auditoria', 'Seguridad', 0)
) AS o(CodigoEvento, Modulo, Severidad, EnTransaccion) ON d.CodigoEvento=o.CodigoEvento
WHEN MATCHED THEN UPDATE SET Modulo=o.Modulo, Severidad=o.Severidad, EnTransaccion=o.EnTransaccion
WHEN NOT MATCHED THEN INSERT(CodigoEvento, Modulo, Severidad, EnTransaccion) VALUES(o.CodigoEvento, o.Modulo, o.Severidad, o.EnTransaccion);
