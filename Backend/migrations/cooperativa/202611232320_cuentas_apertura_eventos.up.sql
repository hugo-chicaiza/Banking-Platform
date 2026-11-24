/* E6-01: evoluciona el estado y conserva la apertura de las cuentas existentes. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Cuentas.Cuenta', 'Estado') = 10
BEGIN
    ALTER TABLE Cuentas.Cuenta DROP CONSTRAINT CK_Cuenta_Estado, CK_Cuenta_Cierre;
    ALTER TABLE Cuentas.Cuenta ALTER COLUMN Estado varchar(18) NOT NULL;
    ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Estado
        CHECK (Estado IN ('Activa','Inactiva','Bloqueada','Cerrada','PendienteDeposito','Anulada'));
    ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Cierre
        CHECK (Estado <> 'Cerrada' OR (Saldo=0 AND SaldoRetenido=0 AND FechaCierre IS NOT NULL));
END
IF COL_LENGTH('Cuentas.Cuenta', 'FechaActivacion') IS NULL
    ALTER TABLE Cuentas.Cuenta ADD FechaActivacion datetime2 NULL;
IF COL_LENGTH('Cuentas.Cuenta', 'MontoAperturaAplicado') IS NULL
    ALTER TABLE Cuentas.Cuenta ADD MontoAperturaAplicado decimal(18,2) NOT NULL
        CONSTRAINT DF_Cuenta_MontoAperturaAplicado DEFAULT (0);
IF OBJECT_ID('Cuentas.CK_Cuenta_SinSaldoPendiente', 'C') IS NULL
    ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_SinSaldoPendiente
        CHECK (Estado NOT IN ('PendienteDeposito','Anulada') OR (Saldo=0 AND SaldoRetenido=0));
IF OBJECT_ID('Cuentas.CuentaEvento', 'U') IS NULL
BEGIN
    CREATE TABLE Cuentas.CuentaEvento (
        IdCuentaEvento bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_CuentaEvento PRIMARY KEY,
        IdCuenta int NOT NULL CONSTRAINT FK_CuentaEvento_Cuenta REFERENCES Cuentas.Cuenta(IdCuenta),
        TipoEvento varchar(24) NOT NULL,
        EstadoAnterior varchar(18) NULL,
        EstadoActual varchar(18) NOT NULL,
        Detalle nvarchar(500) NOT NULL,
        RealizadoPor int NOT NULL,
        IdAgencia char(3) NOT NULL,
        FechaEvento datetime2 NOT NULL CONSTRAINT DF_CuentaEvento_Fecha DEFAULT SYSUTCDATETIME()
    );
    CREATE INDEX IX_CuentaEvento_Historial ON Cuentas.CuentaEvento(IdCuenta, FechaEvento, IdCuentaEvento);
    CREATE UNIQUE INDEX UX_CuentaEvento_Apertura ON Cuentas.CuentaEvento(IdCuenta)
        WHERE TipoEvento = 'Apertura';
    EXEC sys.sp_executesql N'CREATE TRIGGER Cuentas.trg_CuentaEvento_Inmutable
        ON Cuentas.CuentaEvento AFTER UPDATE, DELETE AS
        BEGIN SET NOCOUNT ON; THROW 57611, ''El historial de cuenta es inmutable.'', 1; END';
END
EXEC sys.sp_executesql N'
    UPDATE Cuentas.Cuenta SET FechaActivacion=FechaApertura
    WHERE Estado=''Activa'' AND FechaActivacion IS NULL;
    INSERT Cuentas.CuentaEvento (IdCuenta,TipoEvento,EstadoActual,Detalle,RealizadoPor,IdAgencia,FechaEvento)
    SELECT c.IdCuenta,''Apertura'',c.Estado,N''Carga inicial de apertura'',c.CreadoPor,c.IdAgencia,c.FechaApertura
    FROM Cuentas.Cuenta AS c WITH (UPDLOCK,HOLDLOCK)
    WHERE NOT EXISTS(SELECT 1 FROM Cuentas.CuentaEvento AS e WITH (UPDLOCK,HOLDLOCK)
                     WHERE e.IdCuenta=c.IdCuenta AND e.TipoEvento=''Apertura'');';
COMMIT TRANSACTION;
