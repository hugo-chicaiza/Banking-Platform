/* E1-14 · Revierte el catálogo sin modificar los registros de auditoría. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57205,'Falta confirmar la base destino de la migracion.',1;

DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento = 'ORG_EXPORTACION';
