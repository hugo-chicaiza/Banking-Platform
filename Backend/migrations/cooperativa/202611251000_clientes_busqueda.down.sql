/* E5-05 abajo (solo fuera de producción). */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57505, 'Falta confirmar la base destino de E5-05.', 1;

BEGIN TRANSACTION;
DROP INDEX IF EXISTS IX_Cliente_NombreBusqueda ON Clientes.Cliente;
IF COL_LENGTH('Clientes.Cliente', 'NombreBusqueda') IS NOT NULL
    ALTER TABLE Clientes.Cliente DROP COLUMN NombreBusqueda;
IF COL_LENGTH('Clientes.Cliente', 'IdAgenciaRegistro') IS NOT NULL
BEGIN
    ALTER TABLE Clientes.Cliente DROP CONSTRAINT FK_Cliente_AgenciaRegistro;
    ALTER TABLE Clientes.Cliente DROP COLUMN IdAgenciaRegistro;
END;
COMMIT TRANSACTION;
