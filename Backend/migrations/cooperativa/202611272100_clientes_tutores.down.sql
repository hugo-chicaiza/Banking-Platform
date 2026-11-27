SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de tutores.', 1;

IF EXISTS (SELECT 1 FROM Clientes.ClienteRelacion WHERE TipoRespaldoAlta IS NOT NULL OR TipoRespaldoFin IS NOT NULL)
    THROW 57508, 'Conserve los tipos de respaldo antes de revertir la migracion.', 1;

ALTER TABLE Clientes.ClienteRelacion DROP COLUMN TipoRespaldoAlta, TipoRespaldoFin;
