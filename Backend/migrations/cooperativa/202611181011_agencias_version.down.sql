SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id=OBJECT_ID(N'Organizacion.Agencia') AND name=N'VersionE010' AND system_type_id=189
)
    ALTER TABLE Organizacion.Agencia DROP COLUMN VersionE010;
