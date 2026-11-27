/* El fin efectivo de los firmantes creados por este flujo es el primer día sin autorización. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de firmantes.', 1;

IF COL_LENGTH('Clientes.ClienteRelacion','AlcanceFirma') IS NULL
BEGIN
    ALTER TABLE Clientes.ClienteRelacion ADD
        AlcanceFirma nvarchar(250) NULL, RespaldoAlta nvarchar(250) NULL,
        RespaldoFin nvarchar(250) NULL, FinalizadoPor int NULL, FinalizadoEn datetime2 NULL;
END;
