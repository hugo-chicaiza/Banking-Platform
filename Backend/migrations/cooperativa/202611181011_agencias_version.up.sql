SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF OBJECT_ID(N'Organizacion.Agencia', N'U') IS NULL
    THROW 57351, 'Falta Organizacion.Agencia.', 1;
IF COL_LENGTH(N'Organizacion.Agencia', N'VersionE010') IS NULL
    ALTER TABLE Organizacion.Agencia ADD VersionE010 rowversion NOT NULL;
ELSE IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id=OBJECT_ID(N'Organizacion.Agencia') AND name=N'VersionE010' AND system_type_id=189
)
    THROW 57351, 'VersionE010 debe ser rowversion.', 1;
