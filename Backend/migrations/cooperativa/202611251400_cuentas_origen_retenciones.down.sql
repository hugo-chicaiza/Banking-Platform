SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;
BEGIN TRANSACTION;
IF COL_LENGTH('Cuentas.Retencion', 'IdSubProductoOrigen') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM Cuentas.Retencion WITH (TABLOCKX, HOLDLOCK))
        THROW 57650, 'Hay retenciones con información del origen contable.', 1;
    ALTER TABLE Cuentas.Retencion DROP CONSTRAINT FK_Retencion_SubProductoOrigen;
    ALTER TABLE Cuentas.Retencion DROP COLUMN IdSubProductoOrigen;
END;
COMMIT;
