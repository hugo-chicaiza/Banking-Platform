SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;
IF OBJECT_ID('Cuentas.Retencion','U') IS NOT NULL
    EXEC(N'IF EXISTS (SELECT 1 FROM Cuentas.Retencion) THROW 57650, ''Hay retenciones registradas'', 1;');
DROP VIEW IF EXISTS Cuentas.vw_RetenidoDescuadrado;
DROP TABLE IF EXISTS Cuentas.Retencion;
DROP TABLE IF EXISTS Catalogo.TipoRetencion;
