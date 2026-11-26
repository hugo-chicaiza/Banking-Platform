/* E5-07 abajo (solo fuera de producción). */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57507, 'Falta confirmar la base destino de E5-07.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Clientes.Cliente', 'MotivoEstado') IS NOT NULL
    ALTER TABLE Clientes.Cliente DROP COLUMN MotivoEstado;
COMMIT TRANSACTION;
