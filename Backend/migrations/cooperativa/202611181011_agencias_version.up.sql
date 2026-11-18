SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF OBJECT_ID(N'Organizacion.Agencia', N'U') IS NULL
    THROW 57351, 'Falta Organizacion.Agencia.', 1;
IF COL_LENGTH(N'Organizacion.Agencia', N'VersionFila') IS NULL
BEGIN
    IF EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'Organizacion.Agencia', N'U') AND system_type_id = 189
    )
        THROW 57351, 'Agencia ya tiene otra columna rowversion. Revise el esquema.', 1;
    ALTER TABLE Organizacion.Agencia ADD VersionFila rowversion NOT NULL;
END
ELSE IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id=OBJECT_ID(N'Organizacion.Agencia') AND name=N'VersionFila' AND system_type_id=189 AND is_nullable=0
)
    THROW 57351, 'VersionFila debe ser rowversion NOT NULL.', 1;
