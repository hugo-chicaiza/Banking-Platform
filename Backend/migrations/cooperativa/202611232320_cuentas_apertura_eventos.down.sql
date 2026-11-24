/* E6-01: protege estados y eventos registrados por la aplicación. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;

BEGIN TRANSACTION;
IF EXISTS(SELECT 1 FROM Cuentas.Cuenta WITH (TABLOCKX,HOLDLOCK) WHERE Estado IN ('PendienteDeposito','Anulada'))
    THROW 57611, 'Existen cuentas en los estados nuevos.', 1;
IF OBJECT_ID('Cuentas.CuentaEvento','U') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'IF EXISTS(SELECT 1 FROM Cuentas.CuentaEvento WITH (TABLOCKX,HOLDLOCK)
        WHERE TipoEvento <> ''Apertura'' OR Detalle <> N''Carga inicial de apertura'')
        THROW 57611, ''Existen eventos de cuenta que deben conservarse.'', 1;';
    DROP TABLE Cuentas.CuentaEvento;
END
ALTER TABLE Cuentas.Cuenta DROP CONSTRAINT IF EXISTS CK_Cuenta_SinSaldoPendiente, DF_Cuenta_MontoAperturaAplicado;
ALTER TABLE Cuentas.Cuenta DROP COLUMN IF EXISTS FechaActivacion, MontoAperturaAplicado;
IF COL_LENGTH('Cuentas.Cuenta', 'Estado') = 18
BEGIN
    ALTER TABLE Cuentas.Cuenta DROP CONSTRAINT CK_Cuenta_Estado, CK_Cuenta_Cierre;
    ALTER TABLE Cuentas.Cuenta ALTER COLUMN Estado varchar(10) NOT NULL;
    ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Estado
        CHECK (Estado IN ('Activa','Inactiva','Bloqueada','Cerrada'));
    ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Cierre
        CHECK (Estado <> 'Cerrada' OR (Saldo=0 AND SaldoRetenido=0 AND FechaCierre IS NOT NULL));
END
COMMIT TRANSACTION;
