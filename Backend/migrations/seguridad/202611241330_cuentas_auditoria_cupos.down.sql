SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57613, 'Falta confirmar la base destino de E6-03.', 1;

DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento = 'CTA_CUPO_CAMBIADO'
    AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria WHERE CodigoEvento = 'CTA_CUPO_CAMBIADO');
