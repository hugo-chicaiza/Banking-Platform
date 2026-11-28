SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de Tarjetas.TarjetaNumeroCifrado.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Tarjetas.TarjetaNumeroCifrado', N'U') IS NOT NULL
   AND EXISTS (SELECT 1 FROM Tarjetas.TarjetaNumeroCifrado)
    THROW 57720, 'No se puede retirar la custodia PAN mientras contiene datos.', 1;

IF OBJECT_ID(N'Tarjetas.TarjetaNumeroCifrado', N'U') IS NOT NULL
    DROP TABLE Tarjetas.TarjetaNumeroCifrado;
COMMIT TRANSACTION;
