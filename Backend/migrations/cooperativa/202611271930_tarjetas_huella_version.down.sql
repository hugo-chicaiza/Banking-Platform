SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de VersionClaveHuella.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH(N'Tarjeta.Tarjeta', N'VersionClaveHuella') IS NOT NULL
   OR COL_LENGTH(N'Tarjeta.Tarjeta', N'ReferenciaClaveHuella') IS NOT NULL
BEGIN
    IF COL_LENGTH(N'Tarjeta.Tarjeta', N'VersionClaveHuella') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM Tarjeta.Tarjeta
           WHERE VersionClaveHuella IS NOT NULL
       )
        THROW 57721, 'Las huellas versionadas deben conservar sus metadatos.', 1;
    IF COL_LENGTH(N'Tarjeta.Tarjeta', N'ReferenciaClaveHuella') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM Tarjeta.Tarjeta
           WHERE ReferenciaClaveHuella IS NOT NULL
       )
        THROW 57721, 'Las huellas versionadas deben conservar sus metadatos.', 1;
    IF COL_LENGTH(N'Tarjeta.Tarjeta', N'ReferenciaClaveHuella') IS NOT NULL
        ALTER TABLE Tarjeta.Tarjeta DROP COLUMN ReferenciaClaveHuella;
    IF COL_LENGTH(N'Tarjeta.Tarjeta', N'VersionClaveHuella') IS NOT NULL
        ALTER TABLE Tarjeta.Tarjeta DROP COLUMN VersionClaveHuella;
END;
COMMIT TRANSACTION;
