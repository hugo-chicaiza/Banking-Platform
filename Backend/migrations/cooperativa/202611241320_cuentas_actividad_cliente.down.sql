SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57640, 'Falta confirmar la base destino de E6-04.', 1;

BEGIN TRANSACTION;
DROP TABLE IF EXISTS Catalogo.MotivoBloqueoCuenta;
DROP TRIGGER IF EXISTS Cuentas.trg_Movimiento_ActividadCliente;
DROP VIEW IF EXISTS Cuentas.vw_MovimientoIniciadoPorCliente;
DROP INDEX IF EXISTS IX_Cuenta_ActividadCliente ON Cuentas.Cuenta;
IF COL_LENGTH('Cuentas.Cuenta','FechaUltimoMovimientoCliente') IS NOT NULL
    ALTER TABLE Cuentas.Cuenta DROP COLUMN FechaUltimoMovimientoCliente;
COMMIT TRANSACTION;
