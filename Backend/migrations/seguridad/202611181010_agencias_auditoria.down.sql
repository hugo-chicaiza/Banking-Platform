-- Development only. Refuse to discard recorded snapshots.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF OBJECT_ID(N'Auditoria.CK_Auditoria_E010_DetalleJson', N'C') IS NOT NULL
BEGIN
    BEGIN TRANSACTION;
    EXEC sys.sp_executesql N'IF EXISTS (SELECT 1 FROM Auditoria.Auditoria WITH (TABLOCKX, HOLDLOCK)
        WHERE DetalleJson IS NOT NULL) THROW 57351, ''Hay eventos estructurados; preserve la bitacora.'', 1;';
    ALTER TABLE Auditoria.Auditoria DROP CONSTRAINT CK_Auditoria_E010_DetalleJson;
    ALTER TABLE Auditoria.Auditoria DROP COLUMN DetalleJson;
    COMMIT TRANSACTION;
END;
