-- El parámetro y sus valores se conservan para preservar su configuración e historial.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57190, 'Falta confirmar la base destino de la migracion.', 1;

BEGIN TRANSACTION;
DROP INDEX IF EXISTS UX_Cliente_EmailPrincipal ON Clientes.Cliente;
IF COL_LENGTH('Clientes.Cliente', 'EmailPrincipalNormalizado') IS NOT NULL
    ALTER TABLE Clientes.Cliente DROP COLUMN EmailPrincipalNormalizado;
COMMIT TRANSACTION;
