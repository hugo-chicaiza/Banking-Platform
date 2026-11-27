SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de tutores.', 1;

ALTER TABLE Clientes.ClienteRelacion ADD TipoRespaldoAlta nvarchar(80) NULL,
    TipoRespaldoFin nvarchar(80) NULL;
