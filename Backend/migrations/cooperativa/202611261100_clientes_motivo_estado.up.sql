/* E5-07: motivo del último cambio de estado del cliente. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57507, 'Falta confirmar la base destino de E5-07.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Clientes.Cliente', 'MotivoEstado') IS NULL
    ALTER TABLE Clientes.Cliente ADD MotivoEstado varchar(300) NULL;
COMMIT TRANSACTION;
