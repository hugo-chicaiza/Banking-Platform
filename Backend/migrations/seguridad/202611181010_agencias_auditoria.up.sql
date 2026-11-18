-- SeguridadDB. Preserve the legacy description and store complete snapshots separately.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF OBJECT_ID(N'Auditoria.Auditoria', N'U') IS NULL
    THROW 57351, 'Falta Auditoria.Auditoria.', 1;

IF COL_LENGTH(N'Auditoria.Auditoria', N'DetalleJson') IS NULL
    ALTER TABLE Auditoria.Auditoria ADD DetalleJson nvarchar(max) NULL
        CONSTRAINT CK_Auditoria_E010_DetalleJson CHECK (ISJSON(DetalleJson) = 1);
ELSE IF OBJECT_ID(N'Auditoria.CK_Auditoria_E010_DetalleJson', N'C') IS NULL
    THROW 57351, 'DetalleJson existe con un contrato distinto.', 1;
