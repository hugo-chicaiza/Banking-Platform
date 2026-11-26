SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de firmantes.', 1;

IF COL_LENGTH('Clientes.ClienteRelacion','AlcanceFirma') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM Clientes.ClienteRelacion WHERE AlcanceFirma IS NOT NULL OR RespaldoFin IS NOT NULL)
        THROW 50001, 'Existen respaldos de firmantes. Reversión cancelada.', 1;
    ALTER TABLE Clientes.ClienteRelacion DROP COLUMN AlcanceFirma, RespaldoAlta, RespaldoFin, FinalizadoPor, FinalizadoEn;
END;
