-- Only removes the sequence if it was installed by E0-10.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF EXISTS (
    SELECT 1 FROM sys.extended_properties
    WHERE class = 1 AND major_id = OBJECT_ID(N'Organizacion.SeqAgenciaId', N'SO')
        AND minor_id = 0 AND name = N'E010_Propietario' AND CONVERT(nvarchar(20), value) = N'351'
)
    DROP SEQUENCE Organizacion.SeqAgenciaId;
